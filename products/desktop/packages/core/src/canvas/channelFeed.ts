import type { TaskRunStatus } from "@posthog/shared/domain-types";
import { isTerminalStatus } from "@posthog/shared/domain-types";

const PERMANENT_CHANNEL_FEED_FAILURES = new Set([401, 403, 404]);

export function shouldPollChannelFeed(error: unknown): boolean {
  if (!error || typeof error !== "object" || !("status" in error)) return true;
  const status = (error as { status?: unknown }).status;
  return (
    typeof status !== "number" || !PERMANENT_CHANNEL_FEED_FAILURES.has(status)
  );
}

export function taskFeedRunStatus({
  status,
  environment,
}: {
  status: TaskRunStatus | null | undefined;
  environment: string | null | undefined;
}): TaskRunStatus | null {
  if (!status) return null;
  return environment === "cloud" || isTerminalStatus(status) ? status : null;
}
