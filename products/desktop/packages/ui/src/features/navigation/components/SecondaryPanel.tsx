import { ErrorBoundary } from "@posthog/ui/primitives/ErrorBoundary";
import { ResizableSidebar } from "@posthog/ui/primitives/ResizableSidebar";
import { useNavPanelStore } from "../navPanelStore";
import {
  SECONDARY_PANEL_MIN_WIDTH,
  useSecondaryPanelStore,
} from "../secondaryPanelStore";
import { useSecondaryPanelState } from "../useNavPanels";
import { ActivityFeedPanel } from "./ActivityFeedPanel";
import { SpacePanel } from "./SpacePanel";

/**
 * The second chrome column: a space's lists or the activity feed, between the
 * primary sidebar and the content pane. Which panel shows is view state
 * (navPanelStore); only the width persists.
 */
export function SecondaryPanel() {
  const { destination, open } = useSecondaryPanelState();
  const width = useSecondaryPanelStore((s) => s.width);
  const setWidth = useSecondaryPanelStore((s) => s.setWidth);
  const isResizing = useSecondaryPanelStore((s) => s.isResizing);
  const setIsResizing = useSecondaryPanelStore((s) => s.setIsResizing);

  return (
    <ResizableSidebar
      open={open}
      width={width}
      setWidth={setWidth}
      isResizing={isResizing}
      setIsResizing={setIsResizing}
      side="left"
      minWidth={SECONDARY_PANEL_MIN_WIDTH}
      setOpen={(next) =>
        useNavPanelStore.getState().setPanel(next ? "auto" : "off")
      }
    >
      {/* Inside the content frame now, so it takes the content surface rather
          than the sidebar's chrome — the divider alone separates the two. */}
      <div className="h-full min-h-0 bg-background">
        {destination?.kind === "activity" && <ActivityFeedPanel />}
        {destination?.kind === "space" && (
          <ErrorBoundary
            name="space-panel"
            fallback={null}
            resetKey={destination.channelId}
          >
            <SpacePanel channelId={destination.channelId} />
          </ErrorBoundary>
        )}
      </div>
    </ResizableSidebar>
  );
}
