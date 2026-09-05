import { randomUUID } from "node:crypto";

export const CREDENTIAL_RELAY_TIMEOUT_MS = 120_000;

export interface CredentialRelayConfig {
  emitEvent: (event: Record<string, unknown>) => void;
  timeoutMs?: number;
}

interface PendingRequest {
  resolve: (token: string) => void;
  reject: (error: Error) => void;
  timer: NodeJS.Timeout;
}

export class CredentialRelay {
  private readonly pending = new Map<string, PendingRequest>();
  private completedRequestId: string | null = null;
  private stopped = false;

  constructor(private readonly config: CredentialRelayConfig) {}

  request(credential: string): Promise<string> {
    if (this.stopped) {
      return Promise.reject(new Error("Session is shutting down."));
    }
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
    tokenPromise.catch(() => {});

    this.config.emitEvent({
      type: "credential_request",
      requestId,
      credential,
      expiresAt,
    });
    return tokenPromise;
  }

  resolve(params: {
    requestId: string;
    token?: string;
    error?: string;
  }): boolean {
    const pending = this.pending.get(params.requestId);
    if (!pending) return params.requestId === this.completedRequestId;
    this.pending.delete(params.requestId);
    clearTimeout(pending.timer);
    this.completedRequestId = params.requestId;
    if (params.error) {
      pending.reject(
        new Error("PostHog Desktop could not provide the Claude token."),
      );
    } else if (params.token) {
      pending.resolve(params.token);
    } else {
      pending.reject(new Error("The credential response had no token."));
    }
    return true;
  }

  stop(): void {
    this.stopped = true;
    this.completedRequestId = null;
    for (const [requestId, pending] of this.pending) {
      clearTimeout(pending.timer);
      pending.reject(new Error("Session is shutting down."));
      this.pending.delete(requestId);
    }
  }
}
