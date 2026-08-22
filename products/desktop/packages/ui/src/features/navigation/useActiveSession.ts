import { useRailSurface } from "@posthog/ui/features/canvas/hooks/useRailSurface";
import { useActivityDetailStore } from "@posthog/ui/features/canvas/stores/activityDetailStore";
import { useTaskFeedSelectionStore } from "@posthog/ui/features/canvas/stores/taskFeedSelectionStore";
import { useParams, useSearch } from "@tanstack/react-router";

export interface ActiveSession {
  taskId: string | undefined;
  channelId: string | undefined;
}

/**
 * Which session the chrome around the content pane is about. The route names it
 * everywhere except Activity, which reads a task into the pane without routing.
 */
export function useActiveSession(): ActiveSession {
  const { showsActivityDetail } = useRailSurface();
  const selected = useActivityDetailStore((s) => s.selected);
  const feedSelected = useTaskFeedSelectionStore((s) => s.selected);
  const params = useParams({ strict: false });
  // Canonical task routes carry the space as `?from=` (what used to be the
  // /website/:channelId path segment redirects into it).
  const from = useSearch({ strict: false }).from as string | undefined;

  if (showsActivityDetail) {
    return {
      taskId: selected?.taskId,
      channelId: selected?.channelId ?? undefined,
    };
  }
  if (params.feedId && feedSelected?.feedId === params.feedId) {
    return {
      taskId: feedSelected.taskId,
      channelId: feedSelected.channelId ?? undefined,
    };
  }
  return { taskId: params.taskId, channelId: params.channelId ?? from };
}
