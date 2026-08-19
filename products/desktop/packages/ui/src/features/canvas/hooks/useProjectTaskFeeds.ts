import { useOptionalAuthenticatedClient } from "@posthog/ui/features/auth/authClient";
import { useAuthStateValue } from "@posthog/ui/features/auth/store";
import { useCurrentUser } from "@posthog/ui/features/auth/useCurrentUser";
import {
  type TaskFeed,
  useTaskFeedsStore,
} from "@posthog/ui/features/canvas/stores/taskFeedsStore";
import { useMemo } from "react";

export function useProjectTaskFeeds(): TaskFeed[] {
  const projectId = useAuthStateValue((state) => state.currentProjectId);
  const client = useOptionalAuthenticatedClient();
  const { data: currentUser } = useCurrentUser({ client });
  const ownerId = currentUser?.uuid;
  const feeds = useTaskFeedsStore((state) => state.feeds);
  return useMemo(
    () =>
      projectId === null || ownerId === undefined
        ? []
        : feeds.filter(
            (feed) => feed.projectId === projectId && feed.ownerId === ownerId,
          ),
    [feeds, ownerId, projectId],
  );
}

export function useProjectTaskFeed(feedId: string): TaskFeed | undefined {
  const feeds = useProjectTaskFeeds();
  return feeds.find((feed) => feed.id === feedId);
}
