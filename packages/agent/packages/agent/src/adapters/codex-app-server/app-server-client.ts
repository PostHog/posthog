import { Logger } from "../../utils/logger";
import type { StreamPair } from "../../utils/streams";
import type { JsonRpcMessage, JsonRpcResponse, RequestId } from "./protocol";

export interface AppServerClientHandlers {
  /** Server-pushed notification (no id), e.g. `item/agentMessage/delta`. */
  onNotification?: (method: string, params: unknown) => void;
  /** Server-initiated request (has an id), e.g. an approval; the resolved value is returned as the JSON-RPC result. */
  onRequest?: (method: string, params: unknown) => Promise<unknown>;
  /** Fired once when the stream ends without an explicit close() (process exit). */
  onClose?: () => void;
  logger?: Logger;
}

interface PendingCall {
  resolve: (value: unknown) => void;
  reject: (reason: unknown) => void;
}

/** The subset of the client the agent depends on, so it can be faked in tests. */
export interface AppServerRpc {
  request<T = unknown>(method: string, params?: unknown): Promise<T>;
  notify(method: string, params?: unknown): void;
  close(): Promise<void>;
}

export class AppServerRequestError extends Error {
  constructor(
    readonly code: number,
    message: string,
    readonly data?: unknown,
  ) {
    super(message);
    this.name = "AppServerRequestError";
  }
}

/**
 * Bidirectional newline-delimited JSON-RPC client for the native Codex `app-server` subprocess.
 * Transport-agnostic via a {@link StreamPair} so tests can drive it over in-memory streams.
 */
export class AppServerClient implements AppServerRpc {
  private readonly writer: WritableStreamDefaultWriter<Uint8Array>;
  private readonly encoder = new TextEncoder();
  private readonly pending = new Map<RequestId, PendingCall>();
  private readonly handlers: AppServerClientHandlers;
  private readonly logger: Logger;
  private reader?: ReadableStreamDefaultReader<Uint8Array>;
  private nextId = 1;
  private closed = false;
  private buffer = "";

  constructor(transport: StreamPair, handlers: AppServerClientHandlers = {}) {
    this.handlers = handlers;
    this.logger =
      handlers.logger ??
      new Logger({ debug: false, prefix: "[AppServerClient]" });
    this.writer = transport.writable.getWriter();
    void this.readLoop(transport.readable);
  }

  request<T = unknown>(method: string, params?: unknown): Promise<T> {
    // The read loop is gone once closed, so a registered call could never settle.
    if (this.closed) {
      return Promise.reject(new Error("AppServerClient closed"));
    }
    const id = this.nextId++;
    const promise = new Promise<T>((resolve, reject) => {
      this.pending.set(id, {
        resolve: resolve as (value: unknown) => void,
        reject,
      });
    });
    this.send({ id, method, params });
    return promise;
  }

  notify(method: string, params?: unknown): void {
    if (this.closed) return;
    this.send({ method, params });
  }

  async close(): Promise<void> {
    if (this.closed) return;
    this.closed = true;
    for (const call of this.pending.values()) {
      call.reject(new Error("AppServerClient closed"));
    }
    this.pending.clear();
    try {
      await this.reader?.cancel();
    } catch {
      // reader already released
    }
    try {
      await this.writer.close();
    } catch {
      // writable already closed
    }
  }

  private send(message: JsonRpcMessage): void {
    const line = `${JSON.stringify(message)}\n`;
    this.writer.write(this.encoder.encode(line)).catch((err) => {
      if (!this.closed) {
        this.logger.error("Failed to write app-server message", err);
      }
    });
  }

  private async readLoop(readable: StreamPair["readable"]): Promise<void> {
    this.reader = readable.getReader();
    const decoder = new TextDecoder();
    try {
      while (!this.closed) {
        const { value, done } = await this.reader.read();
        if (done) break;
        this.buffer += decoder.decode(value, { stream: true });
        let newlineIndex = this.buffer.indexOf("\n");
        while (newlineIndex !== -1) {
          const line = this.buffer.slice(0, newlineIndex).trim();
          this.buffer = this.buffer.slice(newlineIndex + 1);
          if (line) this.dispatch(line);
          newlineIndex = this.buffer.indexOf("\n");
        }
      }
    } catch (err) {
      if (!this.closed) {
        this.logger.error("App-server read loop failed", err);
      }
    } finally {
      try {
        this.reader.releaseLock();
      } catch {
        // lock already released by cancel()
      }
      if (!this.closed) {
        // Stream ended without close() (process exited): fail in-flight calls so the turn doesn't hang.
        this.closed = true;
        for (const call of this.pending.values()) {
          call.reject(new Error("codex app-server stream closed"));
        }
        this.pending.clear();
        this.handlers.onClose?.();
      }
    }
  }

  private dispatch(line: string): void {
    let message: JsonRpcMessage;
    try {
      message = JSON.parse(line) as JsonRpcMessage;
    } catch (err) {
      this.logger.warn("Ignoring non-JSON app-server line", { line, err });
      return;
    }

    const id = (message as { id?: unknown }).id;
    const method = (message as { method?: unknown }).method;
    const params = (message as { params?: unknown }).params;
    // Discriminate on id presence, not `typeof id === "number"` — RequestId is
    // string|number, so a string-id server request must still be answered.
    const hasId = id !== undefined && id !== null;

    if (typeof method === "string") {
      if (hasId) {
        void this.handleIncomingRequest(id as RequestId, method, params);
      } else {
        this.handlers.onNotification?.(method, params);
      }
      return;
    }

    if (hasId) {
      this.handleResponse(message as JsonRpcResponse);
    }
  }

  private handleResponse(message: JsonRpcResponse): void {
    const call = this.pending.get(message.id);
    if (!call) {
      this.logger.warn("Response for unknown request id", { id: message.id });
      return;
    }
    this.pending.delete(message.id);
    if (message.error) {
      call.reject(
        new AppServerRequestError(
          message.error.code,
          message.error.message,
          message.error.data,
        ),
      );
    } else {
      call.resolve(message.result);
    }
  }

  private async handleIncomingRequest(
    id: RequestId,
    method: string,
    params: unknown,
  ): Promise<void> {
    if (!this.handlers.onRequest) {
      this.send({
        id,
        error: { code: -32601, message: `Method not handled: ${method}` },
      });
      return;
    }
    try {
      const result = await this.handlers.onRequest(method, params);
      this.send({ id, result });
    } catch (err) {
      this.send({
        id,
        error: {
          code: -32000,
          message: err instanceof Error ? err.message : String(err),
        },
      });
    }
  }
}
