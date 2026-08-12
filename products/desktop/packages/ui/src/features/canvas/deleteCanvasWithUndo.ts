import {
  ANALYTICS_EVENTS,
  type ChannelsSurface,
} from "@posthog/shared/analytics-events";
import { hostClient } from "@posthog/ui/features/canvas/hostClient";
import { usePendingCanvasDeleteStore } from "@posthog/ui/features/canvas/stores/pendingCanvasDeleteStore";
import { toast } from "@posthog/ui/primitives/toast";
import { track } from "@posthog/ui/shell/analytics";

// How long the "Deleted artifact" toast stays up — and, because nothing is sent
// to the host until it expires, how long the user has to undo.
export const CANVAS_DELETE_UNDO_MS = 8000;

// Canvases waiting out their undo window, so a second delete of the same canvas
// (or an undo) can cancel the pending commit. Module-level on purpose: the
// window outlives the component that started it (deleting from the canvas
// itself navigates away immediately).
const pendingTimers = new Map<string, ReturnType<typeof setTimeout>>();

interface DeleteCanvasWithUndoOptions {
  dashboardId: string;
  channelId: string;
  /** Canvas name, for the toast copy. */
  name: string;
  surface: ChannelsSurface;
  /** Refresh the canvas queries once the delete actually lands. */
  invalidate: () => void;
}

/**
 * Delete a canvas with an undo window: the canvas disappears from every list
 * immediately (via the pending store) but the host isn't told until the toast's
 * timer runs out. Undo just cancels that timer, so nothing is ever recreated.
 */
export function deleteCanvasWithUndo({
  dashboardId,
  channelId,
  name,
  surface,
  invalidate,
}: DeleteCanvasWithUndoOptions): void {
  const { markPending, clearPending } = usePendingCanvasDeleteStore.getState();
  const toastId = `canvas-delete-undo-${dashboardId}`;

  // A repeat delete for the same canvas restarts the window rather than
  // stacking two commits.
  const existing = pendingTimers.get(dashboardId);
  if (existing) clearTimeout(existing);

  markPending(dashboardId);

  const commit = async () => {
    pendingTimers.delete(dashboardId);
    try {
      await hostClient().dashboards.delete.mutate({ id: dashboardId });
      track(ANALYTICS_EVENTS.DASHBOARD_ACTION, {
        action_type: "delete",
        surface,
        channel_id: channelId,
        dashboard_id: dashboardId,
        success: true,
      });
      invalidate();
    } catch (error) {
      track(ANALYTICS_EVENTS.DASHBOARD_ACTION, {
        action_type: "delete",
        surface,
        channel_id: channelId,
        dashboard_id: dashboardId,
        success: false,
      });
      toast.error("Couldn't delete canvas", {
        description: error instanceof Error ? error.message : String(error),
      });
    } finally {
      // Either it's gone from the server (and the refreshed list won't include
      // it) or the delete failed and it should come back.
      clearPending(dashboardId);
    }
  };

  pendingTimers.set(
    dashboardId,
    setTimeout(() => void commit(), CANVAS_DELETE_UNDO_MS),
  );

  toast.success("Deleted artifact", {
    id: toastId,
    description: name,
    duration: CANVAS_DELETE_UNDO_MS,
    action: {
      label: "Undo",
      onClick: () => {
        toast.dismiss(toastId);
        undoCanvasDelete({ dashboardId, channelId, surface });
      },
    },
  });
}

function undoCanvasDelete({
  dashboardId,
  channelId,
  surface,
}: {
  dashboardId: string;
  channelId: string;
  surface: ChannelsSurface;
}): void {
  const timer = pendingTimers.get(dashboardId);
  // Nothing to cancel means the window already closed and the delete is in
  // flight or done; leave the pending flag to `commit`.
  if (!timer) return;
  clearTimeout(timer);
  pendingTimers.delete(dashboardId);
  usePendingCanvasDeleteStore.getState().clearPending(dashboardId);
  track(ANALYTICS_EVENTS.DASHBOARD_ACTION, {
    action_type: "delete_undo",
    surface,
    channel_id: channelId,
    dashboard_id: dashboardId,
  });
}
