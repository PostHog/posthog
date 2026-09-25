import {
  ClaudeSubscriptionTokenError,
  type ClaudeSubscriptionTokenErrorCode,
  type PostHogAPIClient,
} from "../posthog-api";
import type { Logger } from "../utils/logger";
import { accessTokenFingerprint } from "./codex-subscription-token";

export const CLAUDE_TOKEN_REQUEST_TIMEOUT_MS = 15_000;

export const CLAUDE_SUBSCRIPTION_TOKEN_PHASE = "claude_subscription_token";

export const CLAUDE_SUBSCRIPTION_TOKEN_FAILED_MESSAGES: Record<
  ClaudeSubscriptionTokenErrorCode,
  string
> = {
  reauth_required:
    "Your Claude token stopped working. Paste a new Claude token in Settings > Harness. Then start the task again.",
  forbidden: "This run could not get your Claude token. Start the task again.",
  request_failed:
    "This run could not get your Claude token. Start the task again.",
};

export function claudeSubscriptionTokenFailureMessage(error: unknown): string {
  const code: ClaudeSubscriptionTokenErrorCode =
    error instanceof ClaudeSubscriptionTokenError
      ? error.code
      : "request_failed";
  return CLAUDE_SUBSCRIPTION_TOKEN_FAILED_MESSAGES[code];
}

export interface ClaudeSubscriptionTokenClientOptions {
  posthogAPI: Pick<PostHogAPIClient, "requestClaudeSubscriptionToken">;
  taskId: string;
  runId: string;
  runToken: string;
  logger?: Logger;
}

export class ClaudeSubscriptionTokenClient {
  private rejectionReport: Promise<void> | null = null;

  constructor(private readonly options: ClaudeSubscriptionTokenClientOptions) {}

  get(): Promise<string> {
    return this.request(null);
  }

  reportRejected(token: string): Promise<void> {
    this.rejectionReport ??= this.request(accessTokenFingerprint(token)).then(
      () => {
        this.options.logger?.warn(
          "Claude rejected the token, but PostHog holds a different one",
        );
      },
      (error: unknown) => {
        const code =
          error instanceof ClaudeSubscriptionTokenError
            ? error.code
            : "unknown";
        this.options.logger?.warn("Reported the rejected Claude token", {
          code,
        });
      },
    );
    return this.rejectionReport;
  }

  private request(rejectedTokenSha256: string | null): Promise<string> {
    return this.options.posthogAPI.requestClaudeSubscriptionToken(
      this.options.taskId,
      this.options.runId,
      this.options.runToken,
      rejectedTokenSha256,
      CLAUDE_TOKEN_REQUEST_TIMEOUT_MS,
    );
  }
}
