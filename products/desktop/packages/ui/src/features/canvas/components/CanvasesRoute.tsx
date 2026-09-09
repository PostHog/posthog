import { BlueprintIcon } from "@phosphor-icons/react";
import {
  Empty,
  EmptyDescription,
  EmptyHeader,
  EmptyMedia,
  EmptyTitle,
} from "@posthog/quill";
import { WebsiteDashboard } from "@posthog/ui/features/canvas/components/WebsiteDashboard";
import { useSelectedCanvasId } from "@posthog/ui/features/canvas/hooks/useSelectedCanvasId";
import { useCanvasViewedStore } from "@posthog/ui/features/canvas/stores/canvasViewedStore";
import { useEffect } from "react";

export function CanvasesRoute() {
  const canvasId = useSelectedCanvasId();
  const markCanvasViewed = useCanvasViewedStore(
    (state) => state.markCanvasViewed,
  );
  useEffect(() => {
    if (canvasId) markCanvasViewed(canvasId, Date.now());
  }, [canvasId, markCanvasViewed]);

  if (canvasId) return <WebsiteDashboard dashboardId={canvasId} />;
  return (
    <div className="flex h-full items-center justify-center p-6">
      <Empty className="border-0">
        <EmptyHeader>
          <EmptyMedia variant="icon">
            <BlueprintIcon />
          </EmptyMedia>
          <EmptyTitle>Pick a canvas</EmptyTitle>
          <EmptyDescription>
            Choose a canvas from the list to open it here.
          </EmptyDescription>
        </EmptyHeader>
      </Empty>
    </div>
  );
}
