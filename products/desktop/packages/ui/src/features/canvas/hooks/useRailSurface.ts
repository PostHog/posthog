import { useChannelsLayout } from "@posthog/ui/features/canvas/hooks/useChannelsLayout";
import {
  type NavRailPane,
  railPaneForMatches,
  railPaneForPath,
  railPaneHasSidebar,
} from "@posthog/ui/features/canvas/railPane";
import { reportSourceHrefFromLocation } from "@posthog/ui/router/reportNavigation";
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
    select: (state) => {
      // The settled location, not the in-flight one: during a pending
      // navigation `location` is already the destination while `matches` still
      // describe the page being left. Pairing the two unmounts the sidebar for
      // one painted frame (the yieldToPaint skeleton) and rebuilds it after.
      const location = state.resolvedLocation ?? state.location;
      const source = reportSourceHrefFromLocation(location);
      return source
        ? railPaneForPath(source.split(/[?#]/)[0])
        : railPaneForMatches(state.matches);
    },
  });
}

/** What the rail is putting on screen. The one answer, for all three surfaces
 *  that need it. */
export function useRailSurface(): RailSurface {
  const channelsLayout = useChannelsLayout();
  const pane = useRailPane();

  return {
    pane,
    hasSidebar: !channelsLayout || railPaneHasSidebar(pane),
    showsActivityDetail: channelsLayout && pane === "activity",
  };
}
