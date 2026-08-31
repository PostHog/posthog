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
  // Select each param on its own. `useParams` without a selector subscribes to
  // the whole param set the nearest match carries for the route chain, so an
  // unrelated param (a settings category) changing would re-render every
  // consumer of this hook.
  const taskId = useParams({ strict: false, select: (p) => p.taskId });
  const channelId = useParams({ strict: false, select: (p) => p.channelId });
  const feedId = useParams({ strict: false, select: (p) => p.feedId });

  if (showsActivityDetail) {
    const taskSelection = selected?.kind === "task" ? selected : null;
    return {
      taskId: taskSelection?.taskId,
      channelId: taskSelection?.channelId ?? undefined,
    };
  }
  if (feedId && feedSelected?.feedId === feedId) {
    return {
      taskId: feedSelected.taskId,
      channelId: feedSelected.channelId ?? undefined,
    };
  }
  return { taskId, channelId };
}

// A saved search names its own tab, so it reports no session.
const NO_SESSION: ActiveSession = { taskId: undefined, channelId: undefined };

/**
 * Which session a browser tab is named after. Reading a result into the pane of
 * a saved search must not rename that tab, so the search reports none.
 */
export function useTabSession(): ActiveSession {
  const params = useParams({ strict: false });
  const session = useActiveSession();
  return params.feedId ? NO_SESSION : session;
}
