import type {
  TaskRunEnvironment,
  TaskRunStatus,
} from "@posthog/shared/domain-types";
import { isTerminalStatus } from "@posthog/shared/domain-types";
import { runStatusForDisplay } from "../tasks/taskStatusPresentation";

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
  runMode,
  isGenerating,
}: {
  status: TaskRunStatus | null | undefined;
  environment: TaskRunEnvironment | null | undefined;
  runMode?: "interactive" | "background" | null;
  isGenerating?: boolean;
}): TaskRunStatus | null {
  const displayStatus = runStatusForDisplay({
    status,
    environment,
    runMode,
    isGenerating,
  });
  if (!displayStatus) return null;
  return environment === "cloud" || isTerminalStatus(displayStatus)
    ? displayStatus
    : null;
}
