import { useChannelsLayout } from "@posthog/ui/features/canvas/hooks/useChannelsLayout";
import {
  type NavRailPane,
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
    // One location decides, and it is the one the app is navigating to. The
    // three things a navigation moves — `location`, `matches`, and
    // `resolvedLocation` — land at different points in the transition, so a
    // rule that reads two of them can answer with a destination neither is on:
    // reading the source off `resolvedLocation` while the fallback read
    // `matches` gave "reports" for the frames after the matches arrived and
    // before the settled location caught up, which took the column off screen
    // and put it back.
    select: (state) => {
      const source = reportSourceHrefFromLocation(state.location);
      return railPaneForPath(
        (source ?? state.location.pathname).split(/[?#]/)[0],
      );
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
