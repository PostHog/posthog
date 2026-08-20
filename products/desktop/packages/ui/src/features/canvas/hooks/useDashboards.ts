import { UNTITLED_CANVAS_NAME } from "@posthog/core/canvas/canvasNaming";
import type {
  CanvasDraft,
  CanvasLocation,
  CanvasSource,
  CanvasVersion,
  DashboardRecord,
} from "@posthog/core/canvas/dashboardSchemas";
import { useHostTRPC } from "@posthog/host-router/react";
import { AUTH_SCOPED_QUERY_META } from "@posthog/ui/features/auth/useCurrentUser";
import { invalidateCanvasLifecycle } from "@posthog/ui/features/canvas/hooks/invalidateCanvasLifecycle";
import { useDashboardEditStore } from "@posthog/ui/features/canvas/stores/dashboardEditStore";
import { toast } from "@posthog/ui/primitives/toast";
import { logger } from "@posthog/ui/shell/logger";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useNavigate } from "@tanstack/react-router";
import { useCallback } from "react";
import {
  SPACE_QUERY_GC_TIME_MS,
  SPACE_QUERY_REFETCH_INTERVAL_MS,
  SPACE_QUERY_STALE_TIME_MS,
} from "./spaceQueryPolicy";

const log = logger.scope("dashboards");

// The naming helpers moved to @posthog/core (CanvasApplicationService uses them
// for auto-naming); re-exported here for the UI surfaces that import them.
export {
  isPlaceholderCanvasName,
  UNTITLED_CANVAS_NAME,
} from "@posthog/core/canvas/canvasNaming";

/** Saved canvases for a channel. */
export function useDashboards(
  channelId: string | undefined,
  options?: { poll?: boolean },
): {
  dashboards: DashboardRecord[];
  isLoading: boolean;
} {
  const trpc = useHostTRPC();
  const { data, isLoading } = useQuery(
    trpc.dashboards.list.queryOptions(
      { channelId: channelId ?? "" },
      {
        enabled: !!channelId,
        gcTime: SPACE_QUERY_GC_TIME_MS,
        meta: AUTH_SCOPED_QUERY_META,
        refetchInterval:
          options?.poll === false ? false : SPACE_QUERY_REFETCH_INTERVAL_MS,
        staleTime: SPACE_QUERY_STALE_TIME_MS,
      },
    ),
  );
  // Canvases inside their delete-undo window stay in the list — surfaces mark
  // them as deleting (see usePendingCanvasDeleteStore) rather than removing a
  // row that Undo would put straight back.
  return { dashboards: data ?? [], isLoading };
}

/**
 * Warm the dashboards-list cache for a channel ahead of opening it (e.g. on
 * hover), so expanding the channel shows its canvases without a cold fetch.
 * Respects the same staleTime, so it no-ops when the data is already fresh.
 */
export function usePrefetchDashboards(): (channelId: string) => void {
  const trpc = useHostTRPC();
  const queryClient = useQueryClient();
  return useCallback(
    (channelId: string) => {
      void queryClient.prefetchQuery(
        trpc.dashboards.list.queryOptions(
          { channelId },
          {
            gcTime: SPACE_QUERY_GC_TIME_MS,
            meta: AUTH_SCOPED_QUERY_META,
            staleTime: SPACE_QUERY_STALE_TIME_MS,
          },
        ),
      );
    },
    [trpc, queryClient],
  );
}

/** A single saved canvas record (metadata + lifecycle pointers). */
export function useDashboard(id: string | undefined): {
  /** `undefined` while unresolved, `null` when the signed-in project has no such canvas. */
  dashboard: DashboardRecord | null | undefined;
  isLoading: boolean;
  isFetching: boolean;
  isError: boolean;
  // Narrowed to the message rather than the tRPC error shape, which is all any caller renders.
  error: { message: string } | null;
  refetch: () => void;
} {
  const trpc = useHostTRPC();
  const { data, isLoading, isFetching, isError, error, refetch } = useQuery(
    trpc.dashboards.get.queryOptions(
      { id: id ?? "" },
      // AUTH_SCOPED_QUERY_META so switching project drops the entry. Without it a cached
      // `null` from the previous project outlives the switch, and a canvas that now resolves
      // still renders as missing.
      { enabled: !!id, staleTime: 5_000, meta: AUTH_SCOPED_QUERY_META },
    ),
  );
  return {
    dashboard: data,
    isLoading,
    isFetching,
    isError,
    error,
    refetch: () => void refetch(),
  };
}

/**
 * Which project owns a canvas that this project does not have.
 *
 * Disabled unless a caller opts in, so the happy path never pays for it. Only the not-found
 * screen has a reason to ask.
 */
export function useCanvasLocation(
  id: string | undefined,
  options?: { enabled?: boolean },
): { location: CanvasLocation | null | undefined; isFetching: boolean } {
  const trpc = useHostTRPC();
  const { data, isFetching } = useQuery(
    trpc.dashboards.location.queryOptions(
      { id: id ?? "" },
      {
        enabled: !!id && (options?.enabled ?? false),
        staleTime: SPACE_QUERY_STALE_TIME_MS,
        meta: AUTH_SCOPED_QUERY_META,
      },
    ),
  );
  return { location: data, isFetching };
}

/** A canvas's source project — the head, or a historical version. */
export function useCanvasSource(input: {
  id: string | undefined;
  versionId?: string;
}): {
  source: CanvasSource | undefined;
  isLoading: boolean;
} {
  const trpc = useHostTRPC();
  const { data, isLoading } = useQuery(
    trpc.dashboards.source.queryOptions(
      { id: input.id ?? "", versionId: input.versionId },
      { enabled: !!input.id },
    ),
  );
  return { source: data, isLoading };
}

/** A canvas's source-version history, newest first (metadata only). */
export function useCanvasVersions(id: string | undefined): {
  versions: CanvasVersion[];
  isLoading: boolean;
} {
  const trpc = useHostTRPC();
  const { data, isLoading } = useQuery(
    trpc.dashboards.versions.queryOptions(
      { id: id ?? "" },
      { enabled: !!id, staleTime: 5_000 },
    ),
  );
  return { versions: data ?? [], isLoading };
}

/** A canvas's staged drafts, newest first, each with its latest build status. */
export function useCanvasDrafts(id: string | undefined): {
  drafts: CanvasDraft[];
  isLoading: boolean;
} {
  const trpc = useHostTRPC();
  const { data, isLoading } = useQuery(
    trpc.dashboards.drafts.queryOptions(
      { id: id ?? "" },
      { enabled: !!id, staleTime: 5_000 },
    ),
  );
  return { drafts: data ?? [], isLoading };
}

/** Create + delete + metadata mutations, invalidating the list + record. */
export function useDashboardMutations() {
  const trpc = useHostTRPC();
  const queryClient = useQueryClient();

  const invalidate = () => {
    void queryClient.invalidateQueries(trpc.dashboards.list.pathFilter());
    void queryClient.invalidateQueries(trpc.dashboards.get.pathFilter());
  };

  const create = useMutation(
    trpc.dashboards.create.mutationOptions({ onSuccess: invalidate }),
  );
  const remove = useMutation(
    trpc.dashboards.delete.mutationOptions({ onSuccess: invalidate }),
  );
  const saveContext = useMutation(
    trpc.dashboards.saveContext.mutationOptions({ onSuccess: invalidate }),
  );
  const revertToVersion = useMutation(
    trpc.dashboards.revertToVersion.mutationOptions({
      // A revert moves the head and queues a rebuild; refresh the reverted
      // canvas's record, build lifecycle, version history, and source so
      // viewers converge — scoped to that canvas, not every open one.
      onSuccess: (_data, variables) => {
        void invalidateCanvasLifecycle(queryClient, trpc, variables.id);
      },
    }),
  );
  const promoteDraft = useMutation(
    trpc.dashboards.promoteDraft.mutationOptions({
      // Promote makes a draft the head and queues (or adopts) its build, and
      // the version leaves the drafts list for published history — refresh the
      // whole lifecycle (which includes drafts) for that canvas.
      onSuccess: (_data, variables) => {
        void invalidateCanvasLifecycle(queryClient, trpc, variables.id);
      },
    }),
  );
  const setGenerationTask = useMutation(
    trpc.dashboards.setGenerationTask.mutationOptions({
      onSuccess: invalidate,
    }),
  );
  const rename = useMutation(
    trpc.dashboards.rename.mutationOptions({ onSuccess: invalidate }),
  );
  const setPinned = useMutation(
    trpc.dashboards.setPinned.mutationOptions({ onSuccess: invalidate }),
  );

  return {
    // Refresh the canvas queries after a mutation that didn't go through this
    // hook (the undo-window delete commits outside React).
    invalidateDashboards: invalidate,
    createDashboard: (channelId: string, name: string, templateId?: string) =>
      create.mutateAsync({ channelId, name, templateId }),
    deleteDashboard: (id: string) => remove.mutateAsync({ id }),
    // Persist the author-written context (markdown) passed to generation tasks.
    saveContext: (id: string, context: string) =>
      saveContext.mutateAsync({ id, context }),
    // Move the canvas's head back to an existing version (and rebuild it).
    revertToVersion: (
      id: string,
      versionId: string,
      expectedCurrentVersionId: string | null,
    ) =>
      revertToVersion.mutateAsync({ id, versionId, expectedCurrentVersionId }),
    // Make a staged draft the canvas's live head (and rebuild it if needed).
    promoteDraft: (
      id: string,
      versionId: string,
      expectedCurrentVersionId: string | null,
    ) => promoteDraft.mutateAsync({ id, versionId, expectedCurrentVersionId }),
    // Record (or clear) the task generating this canvas. Shared on the canvas
    // row so every client polling the canvas sees the in-flight generation.
    setGenerationTask: (id: string, taskId: string | null) =>
      setGenerationTask.mutateAsync({ id, taskId }),
    // Rename a canvas (changes its display title). Used to auto-name a freshly
    // created canvas from its generation prompt.
    renameDashboard: (id: string, name: string) =>
      rename.mutateAsync({ id, name }),
    // Pin (or unpin) a canvas to its channel (shared across users), so the pin
    // shows in the channel's Pinned menu for every member.
    setPinned: (id: string, pinned: boolean) =>
      setPinned.mutateAsync({ id, pinned }),
    isCreating: create.isPending,
    isDeleting: remove.isPending,
    isSavingContext: saveContext.isPending,
    isReverting: revertToVersion.isPending,
    isPromoting: promoteDraft.isPending,
  };
}

/**
 * Create an empty canvas in a channel, enter edit mode, and navigate to it.
 * `opts.channelId` overrides the bound channel, for callers whose channel is
 * provisioned lazily and so has no id at render time (the "me" row).
 */
export function useCreateAndOpenDashboard(
  channelId: string | undefined,
): (opts?: {
  templateId?: string;
  name?: string;
  channelId?: string;
}) => Promise<void> {
  const navigate = useNavigate();
  const { createDashboard } = useDashboardMutations();
  const setEditing = useDashboardEditStore((s) => s.setEditing);

  return useCallback(
    async (opts) => {
      const targetChannelId = opts?.channelId ?? channelId;
      if (!targetChannelId) return;
      const templateId = opts?.templateId ?? "freeform";
      const name = opts?.name ?? UNTITLED_CANVAS_NAME;
      try {
        const record = await createDashboard(targetChannelId, name, templateId);
        setEditing(record.id, true);
        await navigate({
          to: "/website/$channelId/dashboards/$dashboardId",
          params: { channelId: targetChannelId, dashboardId: record.id },
        });
      } catch (error) {
        log.error("Failed to create canvas", { error });
        toast.error("Couldn't create canvas", {
          description: error instanceof Error ? error.message : String(error),
        });
      }
    },
    [channelId, createDashboard, navigate, setEditing],
  );
}
