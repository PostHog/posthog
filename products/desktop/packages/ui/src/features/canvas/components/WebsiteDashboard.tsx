import { ANALYTICS_EVENTS } from "@posthog/shared/analytics-events";
import { CanvasLoadFailed } from "@posthog/ui/features/canvas/components/CanvasLoadFailed";
import { CanvasNotFound } from "@posthog/ui/features/canvas/components/CanvasNotFound";
import { FreeformCanvasView } from "@posthog/ui/features/canvas/freeform/FreeformCanvasView";
import { GridCanvasView } from "@posthog/ui/features/canvas/grid/GridCanvasView";
import { useDashboard } from "@posthog/ui/features/canvas/hooks/useDashboards";
import { useIsDashboardEditing } from "@posthog/ui/features/canvas/stores/dashboardEditStore";
import { CanvasSkeleton } from "@posthog/ui/router/routeSkeletons";
import { track } from "@posthog/ui/shell/analytics";
import { useEffect, useRef } from "react";

// Renders a canvas's app in a sandboxed iframe (view + edit). Edit mode adds
// the chat panel + version controls; generation runs as a dedicated task. The
// view fetches its own record/source/build lifecycle — including the author
// context, which the side panel edits against the saved record directly.
// Grid-kind canvases render the widget-grid surface instead of the single app.
// A null record is a canvas this project does not have (a share link from
// another project); the views would render it as a real, empty canvas.
export function WebsiteDashboard({
  dashboardId,
  channelId,
}: {
  dashboardId: string;
  channelId?: string;
}) {
  const editing = useIsDashboardEditing(dashboardId);
  const { dashboard, isError, isFetching, error, refetch } =
    useDashboard(dashboardId);
  const viewedDashboardIdRef = useRef<string | undefined>(undefined);

  useEffect(() => {
    if (!dashboard || viewedDashboardIdRef.current === dashboard.id) return;
    viewedDashboardIdRef.current = dashboard.id;
    track(ANALYTICS_EVENTS.CANVAS_VIEWED, {
      channel_id: dashboard.channelId,
      dashboard_id: dashboard.id,
      canvas_kind: dashboard.kind,
      template_id: dashboard.templateId,
    });
  }, [dashboard]);

  if (dashboard === undefined) {
    return isError ? (
      <CanvasLoadFailed error={error} retrying={isFetching} onRetry={refetch} />
    ) : (
      <CanvasSkeleton />
    );
  }
  if (dashboard === null) {
    return <CanvasNotFound channelId={channelId} />;
  }
  if (dashboard.kind === "grid") {
    return <GridCanvasView canvasId={dashboardId} interactive={editing} />;
  }
  return (
    <FreeformCanvasView
      threadId={`dashboard:${dashboardId}`}
      interactive={editing}
    />
  );
}
