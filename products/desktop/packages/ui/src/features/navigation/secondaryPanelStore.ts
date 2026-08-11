import { createSidebarStore } from "@posthog/ui/shell/createSidebarStore";

export const SECONDARY_PANEL_MIN_WIDTH = 220;

/**
 * Width of the secondary panel (the space/activity list column between the
 * primary sidebar and the content pane). Open/closed lives in the URL
 * (navPanelSearch), not here — only the drag width persists.
 */
export const useSecondaryPanelStore = createSidebarStore({
  name: "secondary-panel",
  defaultWidth: 280,
  minWidth: SECONDARY_PANEL_MIN_WIDTH,
});
