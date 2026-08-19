import { useAuthStateValue } from "@posthog/ui/features/auth/store";
import {
  type TaskFeed,
  useTaskFeedsStore,
} from "@posthog/ui/features/canvas/stores/taskFeedsStore";
import { useMemo } from "react";

export function useProjectTaskFeeds(): TaskFeed[] {
  const projectId = useAuthStateValue((state) => state.currentProjectId);
  const feeds = useTaskFeedsStore((state) => state.feeds);
  return useMemo(
    () =>
      projectId === null
        ? []
        : feeds.filter((feed) => feed.projectId === projectId),
    [feeds, projectId],
  );
}

export function useProjectTaskFeed(feedId: string): TaskFeed | undefined {
  const feeds = useProjectTaskFeeds();
  return feeds.find((feed) => feed.id === feedId);
}
