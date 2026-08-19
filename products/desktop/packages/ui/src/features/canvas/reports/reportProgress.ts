import type { TaskRunStatus } from "@posthog/shared/types";
import type { ReportTaskData } from "@posthog/ui/features/inbox/hooks/useReportTasks";

export interface ReportProgressItem {
  key: string;
  label: string;
  description: string;
  status: TaskRunStatus | undefined;
  prUrl: string | null;
}

function groupStatus(entries: ReportTaskData[]): TaskRunStatus | undefined {
  const statuses = entries.map((entry) => entry.task.latest_run?.status);
  if (
    statuses.some((status) => status === "in_progress" || status === "queued")
  ) {
    return "in_progress";
  }
  if (statuses.some((status) => status === "completed")) return "completed";
  if (statuses.some((status) => status === "failed")) return "failed";
  if (statuses.some((status) => status === "cancelled")) return "cancelled";
  return statuses.find((status) => status !== undefined);
}

function statusDescription(
  status: TaskRunStatus | undefined,
  descriptions: {
    running: string;
    completed: string;
    stopped: string;
    pending: string;
  },
): string {
  if (status === "in_progress" || status === "queued")
    return descriptions.running;
  if (status === "completed") return descriptions.completed;
  if (status === "failed" || status === "cancelled")
    return descriptions.stopped;
  return descriptions.pending;
}

export function buildReportProgress(
  reportTasks: ReportTaskData[],
): ReportProgressItem[] {
  const pipelineTasks = reportTasks.filter(
    (entry) => entry.purpose !== "discussion",
  );
  const research = pipelineTasks.filter(
    (entry) => entry.purpose === "research",
  );
  const implementation = pipelineTasks.filter(
    (entry) => entry.purpose === "implementation",
  );
  const other = pipelineTasks.filter((entry) => entry.purpose === "other");
  const items: ReportProgressItem[] = [];

  if (research.length > 0) {
    const status = groupStatus(research);
    items.push({
      key: "investigation",
      label: "Investigation",
      description: statusDescription(status, {
        running: "Analyzing evidence and possible causes.",
        completed: "Evidence and root cause analysis completed.",
        stopped: "The investigation stopped before it completed.",
        pending: "The investigation has not started.",
      }),
      status,
      prUrl: null,
    });
  }

  if (implementation.length > 0) {
    const latest = [...implementation].sort((a, b) =>
      b.startedAt.localeCompare(a.startedAt),
    )[0];
    const status = groupStatus(implementation);
    const prUrl =
      typeof latest?.task.latest_run?.output?.pr_url === "string"
        ? latest.task.latest_run.output.pr_url
        : null;
    items.push({
      key: "implementation",
      label: "Implementation",
      description: prUrl
        ? "A pull request is ready for review."
        : statusDescription(status, {
            running: "The agent is preparing a change.",
            completed: "Implementation completed.",
            stopped: "Implementation stopped before a change was ready.",
            pending: "Implementation has not started.",
          }),
      status,
      prUrl,
    });
  }

  for (const entry of other) {
    items.push({
      key: entry.task.id,
      label: entry.purposeLabel,
      description: entry.task.title || "Task without a title",
      status: entry.task.latest_run?.status,
      prUrl:
        typeof entry.task.latest_run?.output?.pr_url === "string"
          ? entry.task.latest_run.output.pr_url
          : null,
    });
  }

  return items;
}
