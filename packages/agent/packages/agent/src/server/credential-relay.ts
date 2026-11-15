import { randomUUID } from "node:crypto";

export const CREDENTIAL_RELAY_TIMEOUT_MS = 120_000;

export class CredentialRelayError extends Error {
  constructor(readonly code: "cancelled" | "timeout" | "no_token") {
    super(
      code === "cancelled"
        ? "Session is shutting down."
        : code === "timeout"
          ? "The credential request timed out waiting for PostHog Desktop."
          : "PostHog Desktop could not provide the Claude token.",
    );
    this.name = "CredentialRelayError";
  }
}

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
      return Promise.reject(new CredentialRelayError("cancelled"));
    }
    const requestId = randomUUID();
    const timeoutMs = this.config.timeoutMs ?? CREDENTIAL_RELAY_TIMEOUT_MS;
    const expiresAt = new Date(Date.now() + timeoutMs).toISOString();

    const tokenPromise = new Promise<string>((resolve, reject) => {
      const timer = setTimeout(() => {
        this.pending.delete(requestId);
        reject(new CredentialRelayError("timeout"));
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
    if (params.token && !params.error) {
      pending.resolve(params.token);
    } else {
      pending.reject(new CredentialRelayError("no_token"));
    }
    return true;
  }

  stop(): void {
    this.stopped = true;
    this.completedRequestId = null;
    for (const [requestId, pending] of this.pending) {
      clearTimeout(pending.timer);
      pending.reject(new CredentialRelayError("cancelled"));
      this.pending.delete(requestId);
    }
  }
}
