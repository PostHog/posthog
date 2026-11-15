import { LockKeyIcon, ShapesIcon } from "@phosphor-icons/react";
import {
  Empty,
  EmptyDescription,
  EmptyHeader,
  EmptyMedia,
  EmptyTitle,
} from "@posthog/quill";
import { ANALYTICS_EVENTS } from "@posthog/shared/analytics-events";
import { useCanvasAvailability } from "@posthog/ui/features/canvas/hooks/useDashboards";
import { LoadingState } from "@posthog/ui/primitives/LoadingState";
import { track } from "@posthog/ui/shell/analytics";
import { useEffect } from "react";

// Shown in place of a canvas that would not open. A canvas link carries no
// project, so it resolves against whichever project the reader has open. The
// two dead ends look identical from the link alone, so the reader has to be
// told which one they hit before they can do anything about it.
export function CanvasUnavailable({ canvasId }: { canvasId: string }) {
  const { availability, isLoading } = useCanvasAvailability(canvasId);
  const reason = availability === "no_access" ? "no_access" : "missing";

  useEffect(() => {
    if (isLoading) return;
    track(ANALYTICS_EVENTS.CANVAS_UNAVAILABLE, {
      dashboard_id: canvasId,
      reason,
    });
  }, [canvasId, isLoading, reason]);

  if (isLoading) return <LoadingState label="Loading canvas" />;

  const noAccess = reason === "no_access";
  return (
    <div className="flex h-full min-h-0 w-full items-center justify-center p-8">
      <Empty className="border-0">
        <EmptyHeader>
          <EmptyMedia variant="icon">
            {noAccess ? <LockKeyIcon /> : <ShapesIcon />}
          </EmptyMedia>
          <EmptyTitle>
            {noAccess
              ? "You don't have access to this canvas"
              : "Canvas not found"}
          </EmptyTitle>
          <EmptyDescription>
            {noAccess
              ? "It is in a space that has not been shared with you. Ask whoever sent the link to add you to the space, or to move the canvas to a public one."
              : "It may have been deleted, or the link may belong to a different organization or project than the one you have open."}
          </EmptyDescription>
        </EmptyHeader>
      </Empty>
    </div>
  );
}
