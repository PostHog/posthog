import { useChannelsLayout } from "@posthog/ui/features/canvas/hooks/useChannelsLayout";
import {
  type NavRailPane,
  railPaneHasSidebar,
  useNavRailStore,
} from "@posthog/ui/features/canvas/stores/navRailStore";

export interface RailSurface {
  pane: NavRailPane;
  hasSidebar: boolean;
  showsActivityDetail: boolean;
}

/** What the rail is putting on screen. The one answer, for all three surfaces
 *  that need it. */
export function useRailSurface(): RailSurface {
  const channelsLayout = useChannelsLayout();
  const pane = useNavRailStore((s) => s.pane);

  return {
    pane,
    hasSidebar: !channelsLayout || railPaneHasSidebar(pane),
    showsActivityDetail: channelsLayout && pane === "activity",
  };
}
