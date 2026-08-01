import { type ChildProcess, spawn } from "node:child_process";
import { randomUUID } from "node:crypto";
import type { Writable } from "node:stream";
import { StringDecoder } from "node:string_decoder";
import { fileURLToPath } from "node:url";
import {
  RpcClient,
  type RpcClientOptions,
} from "@earendil-works/pi-coding-agent";
import { safePiEnvironment } from "./rpc-environment";
import type { PiQueueSnapshot } from "./types";

export type PiRpcClient = RpcClient & {
  getQueue(): Promise<PiQueueSnapshot>;
  clearQueue(): Promise<PiQueueSnapshot>;
};

export interface PiRpcProviderOptions {
  region?: "us" | "eu" | "dev";
  apiKey: string;
  baseUrl?: string;
}

type RpcClientProcessAccess = {
  process?: ChildProcess;
};

interface RpcClientInternals {
  process?: ChildProcess;
  stopReadingStdout?: () => void;
  stderr: string;
  exitError: Error | null;
  handleLine(line: string): void;
  createProcessExitError(
    code: number | null,
    signal: NodeJS.Signals | null,
  ): Error;
  rejectPendingRequests(error: Error): void;
}

interface PiHostRequest {
  type: "posthog_pi_host_request";
  id: string;
  method: "get_queue" | "clear_queue";
}

interface PiHostResponse {
  type: "posthog_pi_host_response";
  id: string;
  data?: PiQueueSnapshot;
  error?: string;
}

function attachJsonlReader(
  stream: NodeJS.ReadableStream,
  onLine: (line: string) => void,
): () => void {
  const decoder = new StringDecoder("utf8");
  let buffer = "";
  const onData = (chunk: Buffer | string) => {
    buffer += typeof chunk === "string" ? chunk : decoder.write(chunk);
    let newlineIndex = buffer.indexOf("\n");
    while (newlineIndex !== -1) {
      const line = buffer.slice(0, newlineIndex);
      onLine(line.endsWith("\r") ? line.slice(0, -1) : line);
      buffer = buffer.slice(newlineIndex + 1);
      newlineIndex = buffer.indexOf("\n");
    }
  };
  stream.on("data", onData);
  return () => stream.off("data", onData);
}

class SecurePiRpcClient extends RpcClient {
  private readonly hostRequests = new Map<
    string,
    {
      resolve: (snapshot: PiQueueSnapshot) => void;
      reject: (error: Error) => void;
      timeout: ReturnType<typeof setTimeout>;
    }
  >();

  constructor(
    private readonly secureOptions: RpcClientOptions,
    private readonly providerOptions: PiRpcProviderOptions,
  ) {
    super(secureOptions);
  }

  override async start(): Promise<void> {
    const internals = this as unknown as RpcClientInternals;
    if (internals.process) {
      throw new Error("Pi RPC client is already started");
    }

    internals.exitError = null;
    const args = ["--mode", "rpc"];
    if (this.secureOptions.provider) {
      args.push("--provider", this.secureOptions.provider);
    }
    if (this.secureOptions.model) {
      args.push("--model", this.secureOptions.model);
    }
    if (this.secureOptions.args) {
      args.push(...this.secureOptions.args);
    }

    const child = spawn(
      process.execPath,
      [this.secureOptions.cliPath ?? "dist/cli.js", ...args],
      {
        cwd: this.secureOptions.cwd,
        env: {
          ...safePiEnvironment(process.env),
          ELECTRON_RUN_AS_NODE: "1",
        },
        stdio: ["pipe", "pipe", "pipe", "pipe", "ipc"],
      },
    );
    internals.process = child;

    child.stderr?.on("data", (data: Buffer) => {
      internals.stderr += data.toString();
      process.stderr.write(data);
    });
    child.once("exit", (code, signal) => {
      if (internals.process !== child) {
        return;
      }
      const error = internals.createProcessExitError(code, signal);
      internals.exitError = error;
      internals.rejectPendingRequests(error);
      this.rejectHostRequests(error);
    });
    child.on("message", (message: unknown) => this.handleHostResponse(message));
    child.once("error", (error) => {
      if (internals.process !== child) {
        return;
      }
      const processError = new Error(
        `Agent process error: ${error.message}. Stderr: ${internals.stderr}`,
      );
      internals.exitError = processError;
      internals.rejectPendingRequests(processError);
    });
    child.stdin?.on("error", (error) => {
      const stdinError =
        internals.exitError ??
        new Error(
          `Agent process stdin error: ${error.message}. Stderr: ${internals.stderr}`,
        );
      internals.exitError = stdinError;
      internals.rejectPendingRequests(stdinError);
    });
    if (child.stdout) {
      internals.stopReadingStdout = attachJsonlReader(child.stdout, (line) =>
        internals.handleLine(line),
      );
    }

    const bootstrapPipe = child.stdio[3] as Writable | null;
    bootstrapPipe?.on("error", () => {});
    bootstrapPipe?.end(
      JSON.stringify({ providerOptions: this.providerOptions }),
    );

    await new Promise((resolve) => setTimeout(resolve, 100));
    if (child.exitCode !== null) {
      throw (
        internals.exitError ??
        internals.createProcessExitError(child.exitCode, child.signalCode)
      );
    }
  }

  getQueue(): Promise<PiQueueSnapshot> {
    return this.sendHostRequest("get_queue");
  }

  clearQueue(): Promise<PiQueueSnapshot> {
    return this.sendHostRequest("clear_queue");
  }

  private sendHostRequest(
    method: PiHostRequest["method"],
  ): Promise<PiQueueSnapshot> {
    const process = (this as unknown as RpcClientInternals).process;
    if (!process?.connected) {
      return Promise.reject(new Error("Pi RPC host is not connected"));
    }

    const id = randomUUID();
    const request: PiHostRequest = {
      type: "posthog_pi_host_request",
      id,
      method,
    };

    return new Promise((resolve, reject) => {
      const timeout = setTimeout(() => {
        this.hostRequests.delete(id);
        reject(new Error(`Pi RPC host request timed out: ${method}`));
      }, 10_000);
      this.hostRequests.set(id, { resolve, reject, timeout });
      process.send?.(request, (error) => {
        if (!error) {
          return;
        }
        const pending = this.hostRequests.get(id);
        if (pending) {
          clearTimeout(pending.timeout);
          this.hostRequests.delete(id);
        }
        reject(error);
      });
    });
  }

  private handleHostResponse(message: unknown): void {
    const response = message as Partial<PiHostResponse>;
    if (
      response.type !== "posthog_pi_host_response" ||
      typeof response.id !== "string"
    ) {
      return;
    }

    const request = this.hostRequests.get(response.id);
    if (!request) {
      return;
    }
    this.hostRequests.delete(response.id);
    clearTimeout(request.timeout);

    if (typeof response.error === "string") {
      request.reject(new Error(response.error));
      return;
    }
    if (!response.data) {
      request.reject(new Error("Pi RPC host returned an empty queue response"));
      return;
    }
    request.resolve(response.data);
  }

  private rejectHostRequests(error: Error): void {
    for (const request of this.hostRequests.values()) {
      clearTimeout(request.timeout);
      request.reject(error);
    }
    this.hostRequests.clear();
  }
}

export function getPiRpcClientProcess(
  client: PiRpcClient,
): ChildProcess | null {
  return (client as unknown as RpcClientProcessAccess).process ?? null;
}

export type PiRpcClientOptions = Pick<
  RpcClientOptions,
  "cliPath" | "cwd" | "model"
> & {
  sessionFile?: string;
  providerOptions: PiRpcProviderOptions;
};

export function createPiRpcClient(options: PiRpcClientOptions): PiRpcClient {
  const { sessionFile, providerOptions, ...rpcOptions } = options;
  const args = sessionFile ? ["--session-file", sessionFile] : [];
  const cliPath =
    rpcOptions.cliPath ??
    fileURLToPath(new URL("./rpc-host.js", import.meta.url));
  return new SecurePiRpcClient(
    {
      ...rpcOptions,
      args,
      cliPath,
      provider: "posthog",
    },
    providerOptions,
  );
}
