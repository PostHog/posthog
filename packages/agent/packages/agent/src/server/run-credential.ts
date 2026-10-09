import {
  type PostHogAPIClient,
  RunCredentialError,
  type RunCredentialErrorCode,
  type StoredRunCredentialKind,
} from "../posthog-api";
import type { Logger } from "../utils/logger";

export const RUN_CREDENTIAL_REQUEST_TIMEOUT_MS = 15_000;

export interface RunCredentialClientOptions {
  posthogAPI: Pick<PostHogAPIClient, "requestStoredRunCredential">;
  taskId: string;
  runId: string;
  runToken: string;
  logger?: Logger;
}

const CREDENTIAL_NAMES: Record<StoredRunCredentialKind, string> = {
  claude_subscription: "Claude subscription",
};

/** What the run owner reads when the run cannot get the credential it was started with. */
export function runCredentialFailureMessage(
  credential: StoredRunCredentialKind,
  error: unknown,
): string {
  const code: RunCredentialErrorCode =
    error instanceof RunCredentialError ? error.code : "request_failed";
  const name = CREDENTIAL_NAMES[credential];
  if (code === "credential_missing") {
    return `Add your ${name} in Cloud agents settings, then start the run again.`;
  }
  return `This run could not get your ${name} from PostHog. Start the run again.`;
}

/**
 * Fetches the Claude plan token that the run owner stored in PostHog, with
 * the run token as proof that the caller is this run's agent-server. One
 * request per credential: the secret stays in this
 * process's memory for the lifetime of the run, because every CLI process the
 * agent-server starts needs it again.
 *
 * The secret is never logged and never written to disk here. Code that the
 * agent runs in the sandbox has the same UID as this process, so it can read
 * the secret from process memory where the kernel allows that. Keeping it out
 * of argv, the environment and files only removes the easy paths.
 */
export class RunCredentialClient {
  private readonly cached = new Map<StoredRunCredentialKind, string>();
  private readonly inFlight = new Map<
    StoredRunCredentialKind,
    Promise<string>
  >();

  constructor(private readonly options: RunCredentialClientOptions) {}

  async get(credential: StoredRunCredentialKind): Promise<string> {
    const cached = this.cached.get(credential);
    if (cached) return cached;
    const pending = this.inFlight.get(credential);
    if (pending) return pending;
    const request = this.request(credential).finally(() => {
      this.inFlight.delete(credential);
    });
    this.inFlight.set(credential, request);
    return request;
  }

  private async request(credential: StoredRunCredentialKind): Promise<string> {
    const secret = await this.options.posthogAPI.requestStoredRunCredential(
      this.options.taskId,
      this.options.runId,
      this.options.runToken,
      credential,
      RUN_CREDENTIAL_REQUEST_TIMEOUT_MS,
    );
    this.cached.set(credential, secret);
    this.options.logger?.info("Fetched the stored credential of this run", {
      credential,
    });
    return secret;
  }
}
