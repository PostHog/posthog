import { useChannelsLayout } from "@posthog/ui/features/canvas/hooks/useChannelsLayout";
import {
  type NavRailPane,
  railPaneForMatches,
  railPaneForPath,
  railPaneHasSidebar,
} from "@posthog/ui/features/canvas/railPane";
import { reportSourceHref } from "@posthog/ui/router/reportNavigation";
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
      const source = reportSourceHref(state.location);
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
