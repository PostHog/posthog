import {
  getPostHogObjectArtifactMetadata,
  groupRunArtifactVersions,
} from "@posthog/core/canvas/runArtifactSchemas";
import { mergePrUrls, readPrUrls, type TaskRunArtifact } from "@posthog/shared";
import type { Task } from "@posthog/shared/domain-types";
import { useSessionSelector } from "@posthog/ui/features/sessions/sessionStore";
import { useRunArtifacts } from "@posthog/ui/features/sessions/useRunArtifacts";

const NO_ARTIFACTS: TaskRunArtifact[] = [];

function isRunActive(status: string | null | undefined): boolean {
  return status === "queued" || status === "in_progress";
}

/**
 * Whether the agent still has the floor. Callers wait on its falling edge for
 * the moment a turn ends.
 *
 * A session this window is driving answers per turn, through the prompt it has
 * in flight. Run status cannot answer that: a cloud run stays `in_progress`
 * across every turn until the whole run ends, so reading it would hold a
 * between-turns moment open for the length of the session.
 *
 * A run this window is only watching has no turn of its own to read, and there
 * the run's status is the closest thing to one.
 */
export function isAgentWorking({
  hasSession,
  isPromptPending,
  runStatus,
}: {
  /** Whether this window is driving the session, rather than watching a run. */
  hasSession: boolean;
  isPromptPending: boolean;
  runStatus: string | null | undefined;
}): boolean {
  return hasSession ? isPromptPending : isRunActive(runStatus);
}

export function useSessionIsWorking(task: Task | null): boolean {
  const taskId = task?.id;
  const hasSession = useSessionSelector(taskId, (s) => s !== undefined);
  const isPromptPending = useSessionSelector(
    taskId,
    (s) => s?.isPromptPending ?? false,
  );
  const cloudStatus = useSessionSelector(taskId, (s) => s?.cloudStatus);
  return isAgentWorking({
    hasSession,
    isPromptPending,
    runStatus: cloudStatus ?? task?.latest_run?.status,
  });
}

/**
 * The deliverable count from already-resolved sources: undismissed output files
 * in the manifest plus the run's pull requests.
 */
export function countArtifacts({
  manifest,
  taskOutput,
  cloudOutput,
}: {
  manifest: TaskRunArtifact[];
  taskOutput: Record<string, unknown> | null | undefined;
  cloudOutput: Record<string, unknown> | null | undefined;
}): number {
  const files = groupRunArtifactVersions(
    manifest.filter((artifact) => artifact.type === "output"),
  ).filter((group) => !group.dismissed).length;
  const references = new Set(
    manifest.flatMap((artifact) =>
      !artifact.dismissed_at && getPostHogObjectArtifactMetadata(artifact)
        ? [artifact.id ?? `${artifact.type}:${artifact.name}`]
        : [],
    ),
  ).size;
  // A PR the run just opened lands in the session's live output before the task
  // query refetches, so read both sources and dedupe rather than the task alone,
  // or the count misses the PR at the turn boundary the tip waits on.
  const prs = mergePrUrls(
    readPrUrls(taskOutput),
    readPrUrls(cloudOutput),
  ).length;
  return files + references + prs;
}

/**
 * How many deliverables a session has produced: the files it uploaded plus the
 * pull requests it opened. What the artifacts panel lists, minus the canvases
 * and the Slack thread, which only the task's thread messages carry - a query
 * this is not worth firing for a count.
 */
export function useSessionArtifactCount(task: Task | null): number {
  const taskId = task?.id;
  const runId = task?.latest_run?.id;
  const cloudStatus = useSessionSelector(taskId, (s) => s?.cloudStatus);
  const sessionArtifacts = useSessionSelector(taskId, (s) => s?.cloudArtifacts);
  const cloudOutput = useSessionSelector(taskId, (s) => s?.cloudOutput);
  const runStatus = cloudStatus ?? task?.latest_run?.status;
  const { data } = useRunArtifacts(taskId, runId, {
    staleTime: 15_000,
    // A finished upload re-keys the query on its own; this only covers a run
    // whose tool events this window never saw.
    refetchInterval: isRunActive(runStatus) ? 120_000 : false,
  });

  // Same order the footer's popover read them in: the fetch is freshest, the
  // session's own copy arrives with the run-status poll, and the task carries
  // the last thing the list said.
  const manifest =
    data ?? sessionArtifacts ?? task?.latest_run?.artifacts ?? NO_ARTIFACTS;
  return countArtifacts({
    manifest,
    taskOutput: task?.latest_run?.output,
    cloudOutput,
  });
}
