import {
  OUTPUT_ARTIFACT_TYPES,
  parseRunArtifacts,
} from "@posthog/core/canvas/runArtifactSchemas";
import type { TaskRun } from "@posthog/shared/domain-types";
import { useTaskRuns } from "@posthog/ui/features/canvas/hooks/useTaskRuns";
import { usePendingArtifactOpenStore } from "@posthog/ui/features/deep-links/pendingArtifactOpenStore";
import { usePanelLayoutStore } from "@posthog/ui/features/panels/panelLayoutStore";
import { toast } from "@posthog/ui/primitives/toast";
import { useEffect, useRef } from "react";

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
  const initializeTask = usePanelLayoutStore((state) => state.initializeTask);
  const getLayout = usePanelLayoutStore((state) => state.getLayout);
  // The runs poll only runs while a request is waiting on it.
  const { runs, isLoading, refreshRuns } = useTaskRuns(
    request ? taskId : undefined,
  );
  const rechecked = useRef<number | null>(null);

  useEffect(() => {
    if (!request || isLoading) return;
    const open = (found: { runId: string; name: string }): void => {
      // The tab goes into the task's layout, and this hook can run on the first commit, before
      // the panel host has made one. Without it openArtifactTab is a no-op and the request is
      // spent on nothing.
      if (!getLayout(taskId)) {
        initializeTask(taskId);
      }
      openArtifactTab(taskId, {
        runId: found.runId,
        artifactId: request.artifactId,
        name: found.name,
      });
      consume(taskId, request.nonce);
    };

    const found = findArtifactInRuns(runs, request.artifactId);
    if (found) {
      open(found);
      return;
    }
    if (runs.length === 0) return;
    // The manifest can be a few minutes stale, which is the ordinary case for a file that was
    // just produced and linked. Read it again before telling the opener the file is gone.
    if (rechecked.current === request.nonce) return;
    rechecked.current = request.nonce;
    void refreshRuns()
      .then((fresh) => {
        const late = findArtifactInRuns(fresh, request.artifactId);
        if (late) {
          open(late);
          return;
        }
        toast.error("Couldn't find that file", {
          description: "It may have been removed from this task.",
        });
        consume(taskId, request.nonce);
      })
      .catch(() => {
        // Leave the request pending: the poll will try again.
        rechecked.current = null;
      });
  }, [
    consume,
    getLayout,
    initializeTask,
    isLoading,
    openArtifactTab,
    refreshRuns,
    request,
    runs,
    taskId,
  ]);
}
