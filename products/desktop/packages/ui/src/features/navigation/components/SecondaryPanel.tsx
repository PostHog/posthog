import { ErrorBoundary } from "@posthog/ui/primitives/ErrorBoundary";
import { ResizableSidebar } from "@posthog/ui/primitives/ResizableSidebar";
import {
  SECONDARY_PANEL_MIN_WIDTH,
  useSecondaryPanelStore,
} from "../secondaryPanelStore";
import { patchNavPanelSearch, useSecondaryPanelState } from "../useNavPanels";
import { ActivityFeedPanel } from "./ActivityFeedPanel";
import { SpacePanel } from "./SpacePanel";

/**
 * The second chrome column: a space's lists or the activity feed, between the
 * primary sidebar and the content pane. Which panel shows (and whether it's
 * open) lives in the URL; only the width is local, persisted state.
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
      setOpen={(next) => patchNavPanelSearch({ panel: next ? null : "off" })}
    >
      <div className="h-full min-h-0 bg-chrome">
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
