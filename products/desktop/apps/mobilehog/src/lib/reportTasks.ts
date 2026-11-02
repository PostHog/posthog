import { requestErrorStatus } from "@posthog/api-client/fetcher";
import type { PostHogAPIClient } from "@posthog/api-client/posthog-client";
import {
  isTerminalStatus,
  type SignalReportArtefactsResponse,
  type Task,
  type TaskRunArtefactContent,
} from "@posthog/shared/domain-types";

type ReportTaskClient = Pick<
  PostHogAPIClient,
  "getSignalReportArtefacts" | "getTask"
>;

export function implementationTaskIds(
  artefacts: SignalReportArtefactsResponse,
): string[] {
  const ids = new Set<string>();
  for (const artefact of artefacts.results) {
    if (artefact.type !== "task_run") continue;
    const content = artefact.content as TaskRunArtefactContent;
    if (content.product === "signals" && content.type === "implementation") {
      ids.add(content.task_id);
    }
  }
  return [...ids];
}

// Live work is a run still going, or a PR that has not merged yet. Starting
// another task on top of it would open a duplicate PR.
export function isLiveImplementationTask(task: Task): boolean {
  const run = task.latest_run;
  if (!run) return false;
  const prUrl = run.output?.pr_url;
  if (typeof prUrl === "string" && prUrl.length > 0) {
    return run.output?.pr_state !== "merged" && run.output?.pr_merged !== true;
  }
  return !isTerminalStatus(run.status);
}

export async function fetchHasLiveImplementationTask(
  client: ReportTaskClient,
  reportId: string,
): Promise<boolean> {
  // The whole log: a default page can drop the task_run rows.
  const artefacts = await client.getSignalReportArtefacts(reportId, {
    limit: 1000,
  });
  const tasks = await Promise.all(
    implementationTaskIds(artefacts).map((id) =>
      // A deleted task leaves its artefact behind. Skip it, but fail on any
      // other error so unknown state does not read as "no live work".
      client
        .getTask(id)
        .catch((error: unknown) => {
          if (requestErrorStatus(error) === 404) return null;
          throw error;
        }),
    ),
  );
  return tasks.some((task) => task !== null && isLiveImplementationTask(task));
}
