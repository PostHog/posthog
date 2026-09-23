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
import { toast } from "@posthog/ui/primitives/toast";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useCallback, useEffect, useRef } from "react";

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
  useEffect(() => {
    if (!data || !remoteHasCode) return;
    const existing = useCanvasSourceStore.getState().entries[canvasId];
    const idle = !isSourceDirty(existing) && !existing?.saving;
    const missing = !hasEntry && !existing;
    if (
      missing ||
      (existing && existing.baseVersionId !== remoteVersionId && idle)
    ) {
      useCanvasSourceStore
        .getState()
        .load(canvasId, data.project, remoteVersionId);
    }
  }, [data, remoteHasCode, remoteVersionId, canvasId, hasEntry]);

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
  const warned = useRef(false);
  const dirty = isSourceDirty(entry);
  const files = entry?.files;
  const saving = entry?.saving ?? false;
  const failed = entry?.saveError != null;

  useEffect(() => {
    if (!dirty || saving || failed || !files) return;
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
      const save = async (
        expected: string | null,
        attempt: number,
      ): Promise<void> => {
        const result = await mutateAsync({
          id: canvasId,
          project,
          expectedCurrentVersionId: expected,
          prompt: describeChanges(snapshot.changes),
        });
        if (result.status === "saved") {
          useCanvasSourceStore
            .getState()
            .markSaved(
              canvasId,
              snapshot.files,
              result.currentVersionId,
              snapshot.changes.length,
            );
          void invalidateCanvasLifecycle(queryClient, trpc, canvasId);
          return;
        }
        if (attempt > 0) throw new Error("The canvas keeps changing elsewhere");
        if (!warned.current) {
          warned.current = true;
          toast.info("This canvas changed somewhere else", {
            description: "Your latest edits were kept.",
          });
        }
        await save(result.currentVersionId, attempt + 1);
      };
      save(snapshot.baseVersionId, 0).catch((error: unknown) => {
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
  }, [dirty, saving, failed, files, canvasId, mutateAsync, queryClient, trpc]);
}
