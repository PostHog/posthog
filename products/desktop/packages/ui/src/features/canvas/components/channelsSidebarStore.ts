import { CHANNELS_SIDEBAR_MIN_WIDTH } from "@posthog/ui/features/sidebar/constants";
import { createSidebarStore } from "@posthog/ui/shell/createSidebarStore";

// The key carries a version because the chrome's narrower sidebar has to be
// what everyone opens on. A width persisted under the old key — a hand-dragged
// one, or the Code width the previous key adopted on first run — would survive
// rehydration and leave most users on the old proportions, so that key is left
// behind rather than migrated.
export const useChannelsSidebarStore = createSidebarStore({
  name: "channels-sidebar-v2",
  defaultWidth: CHANNELS_SIDEBAR_MIN_WIDTH,
  minWidth: CHANNELS_SIDEBAR_MIN_WIDTH,
});
