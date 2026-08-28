import type { Schemas } from "@posthog/api-client";
import { useAuthenticatedInfiniteQuery } from "@posthog/ui/hooks/useAuthenticatedInfiniteQuery";
import { useMemo } from "react";

export const ARCHIVED_TASKS_PAGE_SIZE = 50;

export interface ArchivedTaskSummaryPage {
  results: Schemas.TaskSummary[];
  requested: number;
}

export function getNextArchivedTaskPage(
  allPages: ArchivedTaskSummaryPage[],
  taskCount: number,
): number | undefined {
  const loaded = allPages.reduce((total, page) => total + page.requested, 0);
  return loaded < taskCount ? loaded : undefined;
}

export function useArchivedTaskSummaries(ids: string[]) {
  const query = useAuthenticatedInfiniteQuery<ArchivedTaskSummaryPage, number>(
    ["tasks", "archived-summaries", ids],
    async (client, offset) => {
      const pageIds = ids.slice(offset, offset + ARCHIVED_TASKS_PAGE_SIZE);
      return {
        results: await client.getTaskSummaries(pageIds),
        requested: pageIds.length,
      };
    },
    {
      enabled: ids.length > 0,
      initialPageParam: 0,
      getNextPageParam: (_lastPage, allPages) =>
        getNextArchivedTaskPage(allPages, ids.length),
    },
  );

  const summaries = useMemo(
    () => query.data?.pages.flatMap((page) => page.results) ?? [],
    [query.data?.pages],
  );
  const loadedCount =
    query.data?.pages.reduce((total, page) => total + page.requested, 0) ?? 0;

  return { ...query, summaries, loadedCount };
}
