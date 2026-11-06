import type { DashboardRecord } from "@posthog/core/canvas/dashboardSchemas";
import { planCanvasQuery } from "@posthog/core/tasks/canvasQuery";
import { parseFeedQuery } from "@posthog/core/tasks/feedQuery";
import { useAllCanvases } from "@posthog/ui/features/canvas/hooks/useDashboards";
import { useFeedQueryContext } from "@posthog/ui/features/canvas/hooks/useTaskFeedResults";
import { useMemo } from "react";

/** Canvases across every visible space that match a `type:canvas` query, newest first. */
export function useCanvasQueryResults(query: string): {
  canvases: DashboardRecord[];
  isLoading: boolean;
} {
  const normalized = query.trim();
  const parsed = useMemo(() => parseFeedQuery(normalized), [normalized]);
  const { context, isLoading: contextLoading } = useFeedQueryContext(parsed);
  const { dashboards, isLoading: canvasesLoading } = useAllCanvases({
    enabled: normalized !== "",
  });

  const canvases = useMemo(() => {
    if (normalized === "" || !context) return [];
    const { matches } = planCanvasQuery(parsed, context);
    return dashboards.filter(matches).sort((a, b) => b.updatedAt - a.updatedAt);
  }, [normalized, parsed, context, dashboards]);

  return {
    canvases,
    isLoading: normalized !== "" && (contextLoading || canvasesLoading),
  };
}
