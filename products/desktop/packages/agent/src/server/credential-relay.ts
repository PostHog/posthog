import { randomUUID } from "node:crypto";

/** How long the sandbox waits for the Desktop to answer a credential request. */
export const CREDENTIAL_RELAY_TIMEOUT_MS = 120_000;

export interface CredentialRelayConfig {
  /** Broadcast an event over the durable stream + SSE (agent-server seam). */
  emitEvent: (event: Record<string, unknown>) => void;
  timeoutMs?: number;
}

interface PendingRequest {
  resolve: (token: string) => void;
  reject: (error: Error) => void;
  timer: NodeJS.Timeout;
}

/**
 * Requests a credential (the user's Claude subscription token) from the
 * creating Desktop and waits for a `credential_response` command, mirroring
 * the MCP relay's request/response correlation (docs/CLOUD-MCP-RELAY.md).
 * The token lives in the pending promise only: never written to disk, never
 * logged, never put in an event.
 */
export class CredentialRelay {
  private readonly pending = new Map<string, PendingRequest>();

  constructor(private readonly config: CredentialRelayConfig) {}

  request(credential: string): Promise<string> {
    const requestId = randomUUID();
    const timeoutMs = this.config.timeoutMs ?? CREDENTIAL_RELAY_TIMEOUT_MS;
    const expiresAt = new Date(Date.now() + timeoutMs).toISOString();

    const tokenPromise = new Promise<string>((resolve, reject) => {
      const timer = setTimeout(() => {
        this.pending.delete(requestId);
        reject(
          new Error(
            "The credential request timed out waiting for PostHog Desktop.",
          ),
        );
      }, timeoutMs);
      timer.unref?.();
      this.pending.set(requestId, { resolve, reject, timer });
    });
    // The caller awaits; an unhandled rejection from a dropped reference would
    // kill the process, so keep a no-op catch on the side promise.
    tokenPromise.catch(() => {});

    this.config.emitEvent({
      type: "credential_request",
      requestId,
      credential,
      expiresAt,
    });
    return tokenPromise;
  }

  /** Resolve a pending request from a `credential_response` command. */
  resolve(params: {
    requestId: string;
    token?: string;
    error?: string;
  }): boolean {
    const pending = this.pending.get(params.requestId);
    if (!pending) return false;
    this.pending.delete(params.requestId);
    clearTimeout(pending.timer);
    if (params.error) {
      pending.reject(new Error(params.error));
    } else if (params.token) {
      pending.resolve(params.token);
    } else {
      pending.reject(new Error("The credential response had no token."));
    }
    return true;
  }

  /** Abandon any pending requests (session shutdown). */
  stop(): void {
    for (const [requestId, pending] of this.pending) {
      clearTimeout(pending.timer);
      pending.reject(new Error("Session is shutting down."));
      this.pending.delete(requestId);
    }
  }
}
