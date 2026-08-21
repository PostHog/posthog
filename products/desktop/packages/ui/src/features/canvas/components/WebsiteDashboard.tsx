import { CanvasLoadFailed } from "@posthog/ui/features/canvas/components/CanvasLoadFailed";
import { CanvasNotFound } from "@posthog/ui/features/canvas/components/CanvasNotFound";
import { FreeformCanvasView } from "@posthog/ui/features/canvas/freeform/FreeformCanvasView";
import { GridCanvasView } from "@posthog/ui/features/canvas/grid/GridCanvasView";
import { useDashboard } from "@posthog/ui/features/canvas/hooks/useDashboards";
import { useIsDashboardEditing } from "@posthog/ui/features/canvas/stores/dashboardEditStore";
import { CanvasSkeleton } from "@posthog/ui/router/routeSkeletons";

// Renders a canvas's app in a sandboxed iframe (view + edit). Edit mode adds
// the chat panel + version controls; generation runs as a dedicated task. The
// view fetches its own record/source/build lifecycle — including the author
// context, which the side panel edits against the saved record directly.
// Grid-kind canvases render the widget-grid surface instead of the single app.
//
// Resolving the record is four states rather than two: undefined while it loads, null when the
// signed-in project has no such canvas (which is what a share link from another project hits),
// and an error when the request failed. Branching here means neither canvas view has to reason
// about a record that never arrived, which is how a 404 used to reach the screen as an empty
// canvas.
export function WebsiteDashboard({
  dashboardId,
  channelId,
}: {
  dashboardId: string;
  channelId?: string;
}) {
  const editing = useIsDashboardEditing(dashboardId);
  const { dashboard, isLoading, isError, error, refetch } =
    useDashboard(dashboardId);

  if (isLoading) {
    return <CanvasSkeleton />;
  }
  if (isError) {
    return <CanvasLoadFailed error={error} onRetry={refetch} />;
  }
  if (!dashboard) {
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
