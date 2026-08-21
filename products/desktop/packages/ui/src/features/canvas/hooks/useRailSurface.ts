import { useChannelsLayout } from "@posthog/ui/features/canvas/hooks/useChannelsLayout";
import {
  type NavRailPane,
  railPaneHasSidebar,
  useNavRailStore,
} from "@posthog/ui/features/canvas/stores/navRailStore";

export interface RailSurface {
  /** The rail's destination. Off the layout there is no rail, so this is inert. */
  pane: NavRailPane;
  /** Whether the column beside the rail is drawn at all. */
  hasSidebar: boolean;
  /** Whether the content pane is reading a feed row rather than its route. */
  showsActivityDetail: boolean;
}

/**
 * What the rail is currently putting on screen.
 *
 * The single answer to that question. Three surfaces need it — the app shell
 * frames itself around whether a column is drawn, the sidebar decides whether
 * to draw one, the space layout decides whether to render a route or a feed
 * row — and when they each derived it, they drifted: the shell framed itself
 * around a sidebar the sidebar had already declined to render.
 */
export function useRailSurface(): RailSurface {
  const channelsLayout = useChannelsLayout();
  const pane = useNavRailStore((s) => s.pane);

  return {
    pane,
    hasSidebar: !channelsLayout || railPaneHasSidebar(pane),
    showsActivityDetail: channelsLayout && pane === "activity",
  };
}
