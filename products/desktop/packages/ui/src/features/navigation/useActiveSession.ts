import { useRailSurface } from "@posthog/ui/features/canvas/hooks/useRailSurface";
import { useActivitySelection } from "@posthog/ui/features/canvas/stores/activityDetailStore";
import { useTaskFeedSelectionStore } from "@posthog/ui/features/canvas/stores/taskFeedSelectionStore";
import { useParams } from "@tanstack/react-router";

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
  const selected = useActivitySelection();
  const feedSelected = useTaskFeedSelectionStore((s) => s.selected);
  const params = useParams({ strict: false });

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
  return { taskId: params.taskId, channelId: params.channelId };
}
