import {
  SESSION_SERVICE,
  type SessionService,
} from "@posthog/core/sessions/sessionService";
import { useService } from "@posthog/di/react";
import { ANALYTICS_EVENTS } from "@posthog/shared/analytics-events";
import {
  SessionSummaryPanelView,
  type SessionSummaryState,
} from "@posthog/ui/features/sessions/components/SessionSummaryPanelView";
import {
  SESSION_SUMMARY_LABEL,
  startSessionSummary,
} from "@posthog/ui/features/sessions/sessionSummary";
import { useSideQuestionStore } from "@posthog/ui/features/sessions/sideQuestionStore";
import { toast } from "@posthog/ui/primitives/toast";
import { track } from "@posthog/ui/shell/analytics";

interface SessionSummaryPanelProps {
  taskId: string;
  /** The task's current run. A summary written for a prior run is hidden. */
  taskRunId?: string;
}

/**
 * The carry-over summary, pinned above the composer that started it. The
 * summary lives only in view state, so this panel both shows it and removes
 * it. Nothing here blocks the conversation underneath.
 */
export function SessionSummaryPanel({
  taskId,
  taskRunId,
}: SessionSummaryPanelProps) {
  const entry = useSideQuestionStore((s) => s.byTaskId[taskId]);
  const dismiss = useSideQuestionStore((s) => s.dismiss);
  const sessionService = useService<SessionService>(SESSION_SERVICE);

  if (!entry || entry.kind !== "summary") return null;
  if (entry.taskRunId !== taskRunId) return null;

  const report = (action: "copied" | "dismissed" | "stopped_waiting"): void => {
    track(ANALYTICS_EVENTS.SESSION_SUMMARY_ACTION, {
      task_id: taskId,
      action,
      wait_ms: Date.now() - entry.askedAt,
    });
  };

  const state: SessionSummaryState =
    entry.status === "done"
      ? { status: "done", summary: entry.answer }
      : entry.status === "error"
        ? { status: "error", error: entry.error }
        : { status: "pending" };

  const copySummary = async (): Promise<void> => {
    if (entry.status !== "done") return;
    try {
      await navigator.clipboard.writeText(entry.answer);
      report("copied");
      toast.success("Summary copied");
    } catch {
      toast.error("Couldn't copy the summary");
    }
  };

  return (
    <SessionSummaryPanelView
      title={entry.label ?? SESSION_SUMMARY_LABEL}
      state={state}
      onCopy={() => void copySummary()}
      onRetry={() =>
        startSessionSummary(sessionService, taskId, entry.taskRunId, "retry")
      }
      onDismiss={() => {
        report(entry.status === "pending" ? "stopped_waiting" : "dismissed");
        dismiss(taskId);
      }}
    />
  );
}
