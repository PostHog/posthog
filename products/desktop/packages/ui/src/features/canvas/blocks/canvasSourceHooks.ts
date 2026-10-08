import {
  CANVAS_ENTRY_PATH,
  type CanvasStarter,
  canvasCapabilities,
  starterProject,
} from "@posthog/core/canvas/blockLibrary/blockProject";
import { useHostTRPC } from "@posthog/host-router/react";
import {
  describeChanges,
  isSourceDirty,
  useCanvasSourceEntry,
  useCanvasSourceStore,
} from "@posthog/ui/features/canvas/blocks/canvasSourceStore";
import { invalidateCanvasLifecycle } from "@posthog/ui/features/canvas/hooks/invalidateCanvasLifecycle";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useCallback, useEffect } from "react";

const SOURCE_POLL_MS = 4_000;
const SAVE_DEBOUNCE_MS = 700;

export type CanvasSourceLoad = "loading" | "ready" | "empty";

export function useCanvasSourceSync(
  canvasId: string,
  enabled: boolean,
): CanvasSourceLoad {
  const trpc = useHostTRPC();
  const entry = useCanvasSourceEntry(canvasId);
  const { data, isLoading } = useQuery(
    trpc.dashboards.source.queryOptions(
      { id: canvasId },
      {
        enabled,
        refetchInterval: enabled ? SOURCE_POLL_MS : false,
        staleTime: 1_000,
      },
    ),
  );
  const remoteVersionId = data?.currentVersionId ?? null;
  const remoteHasCode = !!data?.project.files[CANVAS_ENTRY_PATH]?.trim();

  const hasEntry = !!entry;
  const idle = !isSourceDirty(entry) && !entry?.saving;
  useEffect(() => {
    if (!data || !remoteHasCode) return;
    const existing = useCanvasSourceStore.getState().entries[canvasId];
    const missing = !hasEntry && !existing;
    const stale =
      !!existing && existing.baseVersionId !== remoteVersionId && idle;
    if (missing || stale) {
      useCanvasSourceStore
        .getState()
        .load(canvasId, data.project, remoteVersionId);
    }
  }, [data, remoteHasCode, remoteVersionId, canvasId, hasEntry, idle]);

  if (entry) return "ready";
  if (isLoading || !data) return "loading";
  return remoteHasCode ? "loading" : "empty";
}

export function useStartCanvasFromStarter(
  canvasId: string,
): (starter: CanvasStarter) => void {
  return useCallback(
    (starter: CanvasStarter) => {
      const project = starterProject(starter);
      const store = useCanvasSourceStore.getState();
      store.load(canvasId, { ...project, files: {} }, null);
      store.apply(canvasId, project.files);
    },
    [canvasId],
  );
}

export function useCanvasSourceAutosave(canvasId: string): void {
  const trpc = useHostTRPC();
  const queryClient = useQueryClient();
  const entry = useCanvasSourceEntry(canvasId);
  const { mutateAsync } = useMutation(
    trpc.dashboards.publishProject.mutationOptions(),
  );
  const dirty = isSourceDirty(entry);
  const files = entry?.files;
  const saving = entry?.saving ?? false;
  const blocked = entry?.saveError != null || entry?.conflict != null;

  useEffect(() => {
    if (!dirty || saving || blocked || !files) return;
    const timer = setTimeout(() => {
      const store = useCanvasSourceStore.getState();
      const snapshot = store.entries[canvasId];
      if (!snapshot) return;
      store.setSaving(canvasId, true);
      const project = {
        ...snapshot.project,
        files: snapshot.files,
        capabilities: canvasCapabilities(
          snapshot.project.capabilities,
          snapshot.files,
        ),
      };
      mutateAsync({
        id: canvasId,
        project,
        expectedCurrentVersionId: snapshot.baseVersionId,
        prompt: describeChanges(snapshot.changes),
      })
        .then((result) => {
          const latest = useCanvasSourceStore.getState();
          if (result.status === "conflict") {
            latest.setConflict(canvasId, result.currentVersionId);
            return;
          }
          queryClient.setQueryData(
            trpc.dashboards.source.queryKey({ id: canvasId }),
            { project, currentVersionId: result.currentVersionId },
          );
          latest.markSaved(
            canvasId,
            snapshot.files,
            result.currentVersionId,
            snapshot.changes.length,
          );
          void invalidateCanvasLifecycle(queryClient, trpc, canvasId);
        })
        .catch((error: unknown) => {
          useCanvasSourceStore
            .getState()
            .setSaving(
              canvasId,
              false,
              error instanceof Error ? error.message : String(error),
            );
        });
    }, SAVE_DEBOUNCE_MS);
    return () => clearTimeout(timer);
  }, [dirty, saving, blocked, files, canvasId, mutateAsync, queryClient, trpc]);
}
