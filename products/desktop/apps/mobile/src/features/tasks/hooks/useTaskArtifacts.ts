import type { TaskRunArtifact } from "@posthog/shared";
import { useQuery } from "@tanstack/react-query";
import { getProjectId } from "@/lib/api";
import { getTaskRun } from "../api";

// Matches the manifest staleness used for attachment previews so both share the
// same ["taskRunArtifacts", …] cache entry and refetch on the same schedule.
const ARTIFACTS_STALE_MS = 50 * 60 * 1000;

/**
 * Lists a run's generated output artifacts. `enabled` should gate on a terminal
 * run status — mirrors desktop, which only fetches the manifest once the run
 * has finished producing files.
 */
export function useTaskArtifacts(
  taskId: string | undefined,
  runId: string | undefined,
  enabled: boolean,
) {
  const projectId = getProjectId();

  return useQuery({
    queryKey: ["taskRunArtifacts", projectId, taskId, runId],
    enabled: enabled && Boolean(taskId && runId),
    staleTime: ARTIFACTS_STALE_MS,
    retry: false,
    queryFn: async (): Promise<TaskRunArtifact[]> =>
      (await getTaskRun(taskId ?? "", runId ?? "")).artifacts ?? [],
    select: (artifacts) => artifacts.filter((a) => a.type === "output"),
  });
}
