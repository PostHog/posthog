import { FreeformCanvasView } from "@posthog/ui/features/canvas/freeform/FreeformCanvasView";
import { useDashboard } from "@posthog/ui/features/canvas/hooks/useDashboards";
import { useIsDashboardEditing } from "@posthog/ui/features/canvas/stores/dashboardEditStore";
import { useFreeformChatStore } from "@posthog/ui/features/canvas/stores/freeformChatStore";
import { useEffect } from "react";

// Renders a canvas's app in a sandboxed iframe (view + edit). Edit mode adds
// the chat panel + version controls; generation runs as a dedicated task. The
// view fetches its own source/build lifecycle — only the author-context buffer
// is seeded here, from the saved record, while the buffer is still untouched.
export function WebsiteDashboard({ dashboardId }: { dashboardId: string }) {
  const editing = useIsDashboardEditing(dashboardId);
  const { dashboard } = useDashboard(dashboardId);
  const seedContext = useFreeformChatStore((s) => s.seedContext);

  const threadId = `dashboard:${dashboardId}`;

  useEffect(() => {
    if (!dashboard) return;
    seedContext(threadId, dashboard.context ?? "");
  }, [dashboard, threadId, seedContext]);

  return <FreeformCanvasView threadId={threadId} interactive={editing} />;
}
