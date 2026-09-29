import { useChannelsLayout } from "@posthog/ui/features/canvas/hooks/useChannelsLayout";
import { useWorkLayout } from "@posthog/ui/features/canvas/hooks/useWorkLayout";
import {
  type NavRailPane,
  railPaneFoldsIntoWork,
  railPaneForHref,
  railPaneHasSidebar,
} from "@posthog/ui/features/canvas/railPane";
import { useWorkActivityStore } from "@posthog/ui/features/canvas/stores/workActivityStore";
import { isInboxTriagePath } from "@posthog/ui/features/inbox/triageRoute";
import { useRouterState } from "@tanstack/react-router";

export interface RailSurface {
  pane: NavRailPane;
  hasSidebar: boolean;
  showsActivityDetail: boolean;
}

/** The rail destination the route names. A string, so the selector's result is
 *  stable and unrelated route changes don't re-render every consumer. */
export function useRailPane(): NavRailPane {
  return useRouterState({
    // One location decides. `location`, `matches` and `resolvedLocation` land
    // at different points in a transition, so a rule reading two of them
    // answers with a destination neither is on, and the column blinks.
    select: (state) => railPaneForHref(state.location.href),
  });
}

/** What the rail is putting on screen. The one answer, for all three surfaces
 *  that need it. */
export function useRailSurface(): RailSurface {
  const channelsLayout = useChannelsLayout();
  const workLayout = useWorkLayout();
  const workActivityOpen = useWorkActivityStore((state) => state.open);
  const pane = useRailPane();
  const inTriage = useRouterState({
    select: (state) => isInboxTriagePath(state.location.pathname),
  });
  const workSidebar =
    workLayout && (railPaneFoldsIntoWork(pane) || workActivityOpen);

  return {
    pane,
    hasSidebar:
      !inTriage && (!channelsLayout || railPaneHasSidebar(pane) || workSidebar),
    showsActivityDetail: channelsLayout && pane === "activity",
  };
}
