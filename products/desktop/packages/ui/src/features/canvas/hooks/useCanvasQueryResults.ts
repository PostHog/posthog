import type { DashboardRecord } from "@posthog/core/canvas/dashboardSchemas";
import {
  type FeedQueryIssue,
  parseFeedQuery,
  planCanvasQuery,
} from "@posthog/core/tasks/feedQuery";
import { useAllCanvases } from "@posthog/ui/features/canvas/hooks/useDashboards";
import { useFeedQueryContext } from "@posthog/ui/features/canvas/hooks/useTaskFeedResults";
import { useMemo } from "react";

/** Canvases across every visible space that match a `type:canvas` query, newest first. */
export function useCanvasQueryResults(query: string | undefined): {
  canvases: DashboardRecord[];
  errorMessage: string | null;
  isLoading: boolean;
  issues: FeedQueryIssue[];
} {
  const normalized = query?.trim() ?? "";
  const parsed = useMemo(() => parseFeedQuery(normalized), [normalized]);
  const {
    context,
    errorMessage,
    isLoading: contextLoading,
  } = useFeedQueryContext(parsed);
  const { dashboards, isLoading: canvasesLoading } = useAllCanvases({
    enabled: normalized !== "",
  });

  const plan = useMemo(
    () =>
      normalized === "" || !context
        ? undefined
        : planCanvasQuery(parsed, context),
    [normalized, parsed, context],
  );

  const canvases = useMemo(() => {
    if (!plan) return [];
    return dashboards
      .filter((canvas) => plan.matches(canvas))
      .sort((a, b) => b.updatedAt - a.updatedAt);
  }, [dashboards, plan]);

  return {
    canvases,
    errorMessage,
    isLoading: normalized !== "" && (contextLoading || canvasesLoading),
    issues: plan?.issues ?? [],
  };
}
