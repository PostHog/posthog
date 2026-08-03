import { humanizeIdentifier } from "@posthog/core/inbox/activityLog";
import type {
  SignalReportStatus,
  Task,
  TaskRunArtefactContent,
} from "@posthog/shared/types";
import { isTerminalStatus } from "@posthog/shared/types";
import { useAuthenticatedQuery } from "@posthog/ui/hooks/useAuthenticatedQuery";

// Task↔report associations are unlabelled — a task's purpose is derived from the report's
// `task_run` artefacts (the signals pipeline writes product="signals" with one of these types;
// custom agents write their own (product, type) pair).
export type ReportTaskPurpose = "research" | "implementation" | "other";

export interface ReportTaskData {
  task: Task;
  purpose: ReportTaskPurpose;
  /** Human-readable row label — "Research" / "Implementation" / a humanized custom pair. */
  purposeLabel: string;
  startedAt: string;
}

function derivePurpose(taskRun: {
  product: string;
  type: string;
}): { purpose: ReportTaskPurpose; purposeLabel: string } | null {
  if (taskRun.product === "signals") {
    if (taskRun.type === "research") {
      return { purpose: "research", purposeLabel: "Research" };
    }
    if (taskRun.type === "implementation") {
      return { purpose: "implementation", purposeLabel: "Implementation" };
    }
    // Only repo_selection is pipeline plumbing — hide it. All other non-research/non-implementation
    // signals types (scout, discussion, etc.) are report work and should be visible in the Runs
    // section, matching the web frontend's `deriveTaskPurpose` behaviour.
    if (taskRun.type === "repo_selection") {
      return null;
    }
    return {
      purpose: "other",
      purposeLabel: `Signals — ${humanizeIdentifier(taskRun.type)}`,
    };
  }
  return {
    purpose: "other",
    purposeLabel: `${humanizeIdentifier(taskRun.product)} — ${humanizeIdentifier(taskRun.type)}`,
  };
}

const PURPOSE_ORDER: ReportTaskPurpose[] = [
  "implementation",
  "research",
  "other",
];

export function useReportTasks(
  reportId: string,
  reportStatus: SignalReportStatus,
) {
  const isActive =
    reportStatus === "candidate" ||
    reportStatus === "in_progress" ||
    reportStatus === "pending_input";

  return useAuthenticatedQuery<ReportTaskData[]>(
    ["inbox", "report-tasks", reportId],
    async (client) => {
      // task_run artefacts ARE the task↔report association — one entry per associated task,
      // keyed by content.task_id (earliest artefact wins for startedAt). The runtime `type`
      // check is authoritative (the generic fallback artefact keeps `type: string` and
      // defeats static narrowing).
      const artefacts = await client.getSignalReportArtefacts(reportId);
      const taskRunByTaskId = new Map<
        string,
        { product: string; type: string; startedAt: string }
      >();
      for (const artefact of artefacts.results) {
        if (artefact.type !== "task_run") continue;
        const content = artefact.content as TaskRunArtefactContent;
        const existing = taskRunByTaskId.get(content.task_id);
        if (existing && existing.startedAt <= artefact.created_at) continue;
        taskRunByTaskId.set(content.task_id, {
          product: content.product,
          type: content.type,
          startedAt: artefact.created_at,
        });
      }

      const relevant = [...taskRunByTaskId.entries()].flatMap(
        ([taskId, run]) => {
          const derived = derivePurpose(run);
          return derived
            ? [{ taskId, startedAt: run.startedAt, ...derived }]
            : [];
        },
      );

      const tasks = await Promise.all(
        relevant.map(async ({ taskId, startedAt, purpose, purposeLabel }) => {
          const task = await client.getTask(taskId);
          return {
            task,
            purpose,
            purposeLabel,
            startedAt,
          };
        }),
      );
      return tasks.sort(
        (a, b) =>
          PURPOSE_ORDER.indexOf(a.purpose) - PURPOSE_ORDER.indexOf(b.purpose),
      );
    },
    {
      enabled: !!reportId,
      staleTime: isActive ? 5_000 : 10_000,
      refetchInterval: isActive ? 5_000 : false,
    },
  );
}

export function getTaskPrUrl(task: Task): string | null {
  const prUrl = task.latest_run?.output?.pr_url;
  return typeof prUrl === "string" && prUrl.length > 0 ? prUrl : null;
}

/**
 * Find an implementation task linked to the report whose work is still live, so
 * re-engaging the report should resume it rather than spin up a duplicate PR. A
 * task is continuable when its latest run already produced a PR (the report's
 * `implementation_pr_url` may be stale or not yet set, but the task knows) or is
 * still running. A failed/cancelled run with no PR is *not* continuable — the
 * user can legitimately start a fresh attempt there.
 *
 * Prefers a task with a PR over a merely-running one; `reportTasks` is already
 * implementation-first ordered, so the first match wins among equals.
 */
export function findContinuableImplementationTask(
  reportTasks: ReportTaskData[] | undefined,
): Task | null {
  if (!reportTasks) return null;
  // First check any task that already produced a PR — a non-implementation run
  // (e.g. a Discuss task that shipped a PR) should be resumed rather than
  // starting a fresh implementation task, preventing duplicate PRs.
  const anyWithPr = reportTasks.find((t) => getTaskPrUrl(t.task));
  if (anyWithPr) return anyWithPr.task;
  // Fall back to a running implementation task with no PR yet.
  const implementation = reportTasks.filter(
    (t) => t.purpose === "implementation",
  );
  const running = implementation.find((t) => {
    const status = t.task.latest_run?.status;
    return status != null && !isTerminalStatus(status);
  });
  return running?.task ?? null;
}
