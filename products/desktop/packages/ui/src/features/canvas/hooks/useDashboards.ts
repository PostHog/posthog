import type {
  DashboardRecord,
  DashboardSummary,
} from "@posthog/core/canvas/dashboardSchemas";
import type { FreeformVersion } from "@posthog/core/canvas/freeformSchemas";
import { useHostTRPC } from "@posthog/host-router/react";
import { useDashboardEditStore } from "@posthog/ui/features/canvas/stores/dashboardEditStore";
import { toast } from "@posthog/ui/primitives/toast";
import { logger } from "@posthog/ui/shell/logger";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useNavigate } from "@tanstack/react-router";
import { useCallback } from "react";

const log = logger.scope("dashboards");

// Default name for a canvas created without one. Also the marker we use to
// detect a still-unnamed canvas worth auto-naming from its generation prompt.
export const UNTITLED_CANVAS_NAME = "Untitled canvas";

// True when a canvas name is a placeholder (never user-chosen), so auto-naming
// from a generation prompt is safe and won't clobber a real title.
export function isPlaceholderCanvasName(name: string): boolean {
  const trimmed = name.trim();
  return trimmed === UNTITLED_CANVAS_NAME || trimmed === "Untitled dashboard";
}

/** Saved canvases for a channel (file-backed freeform React apps). */
export function useDashboards(channelId: string | undefined): {
  dashboards: DashboardSummary[];
  isLoading: boolean;
} {
  const trpc = useHostTRPC();
  const { data, isLoading } = useQuery(
    trpc.dashboards.list.queryOptions(
      { channelId: channelId ?? "" },
      { enabled: !!channelId, staleTime: 5_000 },
    ),
  );
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
        trpc.dashboards.list.queryOptions({ channelId }, { staleTime: 5_000 }),
      );
    },
    [trpc, queryClient],
  );
}

/** A single saved canvas record (code + metadata). */
export function useDashboard(id: string | undefined): {
  dashboard: DashboardRecord | null | undefined;
  isLoading: boolean;
  isFetching: boolean;
} {
  const trpc = useHostTRPC();
  const { data, isLoading, isFetching } = useQuery(
    trpc.dashboards.get.queryOptions(
      { id: id ?? "" },
      { enabled: !!id, staleTime: 5_000 },
    ),
  );
  return { dashboard: data, isLoading, isFetching };
}

/** Create + fork + save mutations, invalidating the list + record. */
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
  const saveFreeform = useMutation(
    trpc.dashboards.saveFreeform.mutationOptions({ onSuccess: invalidate }),
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
  const ensureHome = useMutation(
    trpc.dashboards.ensureHomeCanvas.mutationOptions({
      onSuccess: () => {
        invalidate();
        // The folder now carries homeCanvasId; refresh the channel list so the
        // sidebar/name-click can route straight to it next time.
        void queryClient.invalidateQueries({ queryKey: ["canvas-channels"] });
      },
    }),
  );

  return {
    createDashboard: (channelId: string, name: string, templateId?: string) =>
      create.mutateAsync({ channelId, name, templateId }),
    deleteDashboard: (id: string) => remove.mutateAsync({ id }),
    // Record (or clear) the task generating this canvas. Shared via the row's
    // meta so every client polling the canvas sees the in-flight generation.
    setGenerationTask: (id: string, taskId: string | null) =>
      setGenerationTask.mutateAsync({ id, taskId }),
    // Rename a canvas (changes its display title). Used to auto-name a freshly
    // created canvas from its generation prompt.
    renameDashboard: (id: string, name: string) =>
      rename.mutateAsync({ id, name }),
    // Pin (or unpin) a canvas to its channel. Shared via the row's meta so the
    // pin shows in the channel's Pinned menu for every member.
    setPinned: (id: string, pinned: boolean) =>
      setPinned.mutateAsync({ id, pinned }),
    // Ensure a channel has its home canvas (creating + seeding it if absent).
    // Idempotent server-side; returns the home canvas record.
    ensureHomeCanvas: (channelId: string) =>
      ensureHome.mutateAsync({ channelId }),
    // Explicitly persist a freeform canvas's current code + history (autosave
    // already runs each turn; this is the manual Save affordance).
    saveFreeformDashboard: (
      id: string,
      code: string,
      versions: FreeformVersion[],
      currentVersionId?: string,
    ) => saveFreeform.mutateAsync({ id, code, versions, currentVersionId }),
    // Fork a freeform canvas: create a fresh freeform record, then copy its
    // source + version history onto it. Returns the new record (to navigate to).
    forkFreeform: async (
      channelId: string,
      name: string,
      code: string,
      versions: FreeformVersion[],
      currentVersionId?: string,
    ): Promise<DashboardRecord> => {
      const record = await create.mutateAsync({
        channelId,
        name,
        templateId: "freeform",
      });
      await saveFreeform.mutateAsync({
        id: record.id,
        code,
        versions,
        currentVersionId,
      });
      return record;
    },
    isSavingFreeform: saveFreeform.isPending,
    isCreating: create.isPending,
    isDeleting: remove.isPending,
  };
}

/**
 * Open a channel's home canvas in the main content pane. Uses the channel's
 * known homeCanvasId when present; otherwise creates one on the fly (backfill
 * for channels made before home canvases existed) before navigating.
 */
export function useOpenHomeCanvas(): (channel: {
  id: string;
  homeCanvasId?: string;
}) => Promise<void> {
  const navigate = useNavigate();
  const { ensureHomeCanvas } = useDashboardMutations();

  return useCallback(
    async (channel) => {
      try {
        const dashboardId =
          channel.homeCanvasId ?? (await ensureHomeCanvas(channel.id)).id;
        await navigate({
          to: "/website/$channelId/dashboards/$dashboardId",
          params: { channelId: channel.id, dashboardId },
        });
      } catch (error) {
        log.error("Failed to open home canvas", { error });
        toast.error("Couldn't open channel home", {
          description: error instanceof Error ? error.message : String(error),
        });
      }
    },
    [navigate, ensureHomeCanvas],
  );
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
