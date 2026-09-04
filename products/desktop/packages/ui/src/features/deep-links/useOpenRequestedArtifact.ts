import {
  OUTPUT_ARTIFACT_TYPES,
  parseRunArtifacts,
} from "@posthog/core/canvas/runArtifactSchemas";
import type { TaskRun } from "@posthog/shared/domain-types";
import { useTaskRuns } from "@posthog/ui/features/canvas/hooks/useTaskRuns";
import { usePendingArtifactOpenStore } from "@posthog/ui/features/deep-links/pendingArtifactOpenStore";
import { usePanelLayoutStore } from "@posthog/ui/features/panels/panelLayoutStore";
import { toast } from "@posthog/ui/primitives/toast";
import { useEffect } from "react";

export function findArtifactInRuns(
  runs: TaskRun[],
  artifactId: string,
): { runId: string; name: string } | null {
  for (const run of runs) {
    for (const file of parseRunArtifacts(
      run.artifacts,
      OUTPUT_ARTIFACT_TYPES,
    )) {
      if (file.id === artifactId && file.name) {
        return { runId: run.id, name: file.name };
      }
    }
  }
  return null;
}

/**
 * Opens the artifact a deep link asked for once this task's runs manifest can
 * name its file and run. Mounted by the task's panel host, so the tab opens
 * into the layout the user is looking at rather than a staged one.
 */
export function useOpenRequestedArtifact(taskId: string): void {
  const request = usePendingArtifactOpenStore(
    (state) => state.requestsByTask[taskId],
  );
  const consume = usePendingArtifactOpenStore(
    (state) => state.consumeArtifactOpen,
  );
  const openArtifactTab = usePanelLayoutStore((state) => state.openArtifactTab);
  // The runs poll only runs while a request is waiting on it.
  const { runs, isLoading } = useTaskRuns(request ? taskId : undefined);

  useEffect(() => {
    if (!request || isLoading) return;
    const found = findArtifactInRuns(runs, request.artifactId);
    if (found) {
      openArtifactTab(taskId, {
        runId: found.runId,
        artifactId: request.artifactId,
        name: found.name,
      });
    } else if (runs.length > 0) {
      toast.error("Couldn't find that file", {
        description: "It may have been removed from this task.",
      });
    } else {
      return;
    }
    consume(taskId, request.nonce);
  }, [consume, isLoading, openArtifactTab, request, runs, taskId]);
}
