import { useRailSurface } from "@posthog/ui/features/canvas/hooks/useRailSurface";
import { useActivityDetailStore } from "@posthog/ui/features/canvas/stores/activityDetailStore";
import { useParams } from "@tanstack/react-router";

export interface ActiveSession {
  taskId: string | undefined;
  channelId: string | undefined;
}

/**
 * Which session the chrome around the content pane is about.
 *
 * The route names it everywhere except Activity, which reads a task into the
 * pane without routing to it — so the title row's actions, the right panel and
 * the mention rules would all be pointed at whatever screen Activity is
 * covering. Resolving that here keeps the exception in one place instead of
 * restating it at every consumer.
 */
export function useActiveSession(): ActiveSession {
  const { showsActivityDetail } = useRailSurface();
  const selected = useActivityDetailStore((s) => s.selected);
  const params = useParams({ strict: false });

  if (showsActivityDetail) {
    return {
      taskId: selected?.taskId,
      channelId: selected?.channelId ?? undefined,
    };
  }
  return { taskId: params.taskId, channelId: params.channelId };
}
