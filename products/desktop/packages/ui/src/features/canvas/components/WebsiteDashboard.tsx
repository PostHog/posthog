import { FreeformCanvasView } from "@posthog/ui/features/canvas/freeform/FreeformCanvasView";
import { GridCanvasView } from "@posthog/ui/features/canvas/grid/GridCanvasView";
import { useDashboard } from "@posthog/ui/features/canvas/hooks/useDashboards";
import { useIsDashboardEditing } from "@posthog/ui/features/canvas/stores/dashboardEditStore";

// Renders a canvas's app in a sandboxed iframe (view + edit). Edit mode adds
// the chat panel + version controls; generation runs as a dedicated task. The
// view fetches its own record/source/build lifecycle — including the author
// context, which the side panel edits against the saved record directly.
// Grid-kind canvases render the widget-grid surface instead of the single app.
export function WebsiteDashboard({ dashboardId }: { dashboardId: string }) {
  const editing = useIsDashboardEditing(dashboardId);
  const { dashboard } = useDashboard(dashboardId);
  if (dashboard?.kind === "grid") {
    return <GridCanvasView canvasId={dashboardId} interactive={editing} />;
  }
  return (
    <FreeformCanvasView
      threadId={`dashboard:${dashboardId}`}
      interactive={editing}
    />
  );
}
