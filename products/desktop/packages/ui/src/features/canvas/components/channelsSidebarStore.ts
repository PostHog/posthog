import { SIDEBAR_MIN_WIDTH } from "@posthog/ui/features/sidebar/constants";
import { createSidebarStore } from "@posthog/ui/shell/createSidebarStore";

export const useChannelsSidebarStore = createSidebarStore({
  name: "channels-sidebar",
  defaultWidth: SIDEBAR_MIN_WIDTH,
  // Also re-clamps the legacy Code width adopted by the migration below.
  // The channels layout raises the floor further, at runtime (ChannelsSidebar).
  minWidth: SIDEBAR_MIN_WIDTH,
});

// One-time migration: the unified layout replaced the Code sidebar (whose
// width persisted under "sidebar-storage") with this store. A user who never
// used the Channels space has no "channels-sidebar" entry yet — adopt their
// old Code width instead of silently resetting them to the default. Once this
// store persists (any set), the migration never runs again.
try {
  if (
    typeof window !== "undefined" &&
    window.localStorage.getItem("channels-sidebar") === null
  ) {
    const legacy = window.localStorage.getItem("sidebar-storage");
    const width: unknown = legacy ? JSON.parse(legacy)?.state?.width : null;
    if (typeof width === "number" && Number.isFinite(width) && width > 0) {
      useChannelsSidebarStore.getState().setWidth(width);
    }
  }
} catch {
  // localStorage may be unavailable or hold malformed JSON; the default is fine.
}
