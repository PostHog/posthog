import { requestErrorStatus } from "@posthog/api-client/fetcher";
import type { PostHogAPIClient } from "@posthog/api-client/posthog-client";
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
export type ReportTaskPurpose =
  | "research"
  | "implementation"
  | "discussion"
  | "other";

export interface ReportTaskData {
  task: Task;
  purpose: ReportTaskPurpose;
  /** Human-readable row label — "Research" / "Implementation" / a humanized custom pair. */
  purposeLabel: string;
  startedAt: string;
}

export function derivePurpose(taskRun: {
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
    if (taskRun.type === "discussion") {
      return { purpose: "discussion", purposeLabel: "Discussion" };
    }
    if (taskRun.type === "repo_selection") {
      // Pipeline plumbing, not report work — never displayed.
      return null;
    }
    // Every other run type (scout today, whatever ships next) is real work on the
    // report, so humanize it rather than drop it.
    return { purpose: "other", purposeLabel: humanizeIdentifier(taskRun.type) };
  }
  return {
    purpose: "other",
    purposeLabel: `${humanizeIdentifier(taskRun.product)} — ${humanizeIdentifier(taskRun.type)}`,
  };
}

const PURPOSE_ORDER: ReportTaskPurpose[] = [
  "implementation",
  "research",
  "discussion",
  "other",
];

/** Matches the web inbox's report-detail fetch, which reads the same full log. */
const FULL_ARTEFACT_LOG_LIMIT = 1000;

type ReportTaskClient = Pick<
  PostHogAPIClient,
  "getSignalReportArtefacts" | "getTask"
>;

export async function fetchReportTasks(
  client: ReportTaskClient,
  reportId: string,
): Promise<ReportTaskData[]> {
  // task_run artefacts ARE the task↔report association — one entry per associated task,
  // keyed by content.task_id (earliest artefact wins for startedAt). The runtime `type`
  // check is authoritative (the generic fallback artefact keeps `type: string` and
  // defeats static narrowing).
  const artefacts = await client.getSignalReportArtefacts(reportId, {
    // Runs are read from the whole log: the scout task_run is written when the report is
    // created, so it is the first row a default page drops.
    limit: FULL_ARTEFACT_LOG_LIMIT,
  });
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

  const relevant = [...taskRunByTaskId.entries()].flatMap(([taskId, run]) => {
    const derived = derivePurpose(run);
    return derived ? [{ taskId, startedAt: run.startedAt, ...derived }] : [];
  });

  const tasks = await Promise.all(
    relevant.map(async ({ taskId, startedAt, purpose, purposeLabel }) => {
      // Nothing deletes the artefact when its task goes, so a deleted task leaves a
      // dangling pointer here. Drop that one row: failing the whole fetch would empty
      // the Runs list and read downstream as "no implementation task", which unlocks
      // the duplicate-PR action. Any other error still fails the query.
      const task = await client.getTask(taskId).catch((error: unknown) => {
        if (requestErrorStatus(error) === 404) return null;
        throw error;
      });
      return task ? { task, purpose, purposeLabel, startedAt } : null;
    }),
  );
  return tasks
    .filter((task) => task !== null)
    .sort(
      (a, b) =>
        PURPOSE_ORDER.indexOf(a.purpose) - PURPOSE_ORDER.indexOf(b.purpose),
    );
}

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
    (client) => fetchReportTasks(client, reportId),
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
 * Has the task's PR merged? A merged PR is history, not live work. `pr_state` is
 * the current signal; runs merged before it existed carry only the legacy
 * `pr_merged` flag (see feedQuery), so honor both.
 */
function isTaskPrMerged(task: Task): boolean {
  const output = task.latest_run?.output;
  if (!output) return false;
  return output.pr_state === "merged" || output.pr_merged === true;
}

/**
 * Find an implementation task linked to the report whose work is still live, so
 * re-engaging the report should resume it rather than spin up a duplicate PR. A
 * task is continuable when its latest run already produced a PR that is still
 * open (the report's `implementation_pr_url` may be stale or not yet set, but the
 * task knows) or is still running. A failed/cancelled run with no PR is *not*
 * continuable, and neither is a *merged* PR — a report that outlived its merged
 * fix (evidence kept arriving) legitimately gets a fresh attempt, not a
 * "continue" of the closed one.
 *
 * Prefers a task with a PR over a merely-running one; `reportTasks` is already
 * implementation-first ordered, so the first match wins among equals.
 */
export function findContinuableImplementationTask(
  reportTasks: ReportTaskData[] | undefined,
): Task | null {
  if (!reportTasks) return null;
  const implementation = reportTasks.filter(
    (t) => t.purpose === "implementation",
  );
  const withPr = implementation.find(
    (t) => getTaskPrUrl(t.task) && !isTaskPrMerged(t.task),
  );
  if (withPr) return withPr.task;
  const running = implementation.find((t) => {
    const status = t.task.latest_run?.status;
    return status != null && !isTerminalStatus(status);
  });
  return running?.task ?? null;
}

/**
 * The report's conversation: the newest discussion task linked to it. A report
 * has one ongoing chat rather than a pile of one-question sessions, so opening
 * the chat panel resumes this task when it exists and only starts a fresh one
 * when it doesn't.
 */
export function findLatestDiscussionTask(
  reportTasks: ReportTaskData[] | undefined,
): Task | null {
  if (!reportTasks) return null;
  const discussions = reportTasks.filter((t) => t.purpose === "discussion");
  if (discussions.length === 0) return null;
  return discussions.reduce((latest, t) =>
    t.startedAt > latest.startedAt ? t : latest,
  ).task;
}

export function findPendingStartedTaskId(
  reportTasks: ReportTaskData[] | undefined,
  startedTaskId: string | null,
): string | null {
  if (!startedTaskId) return null;
  return reportTasks?.some(({ task }) => task.id === startedTaskId)
    ? null
    : startedTaskId;
}
