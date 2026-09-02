import { useOptionalAuthenticatedClient } from "@posthog/ui/features/auth/authClient";
import { useAuthStateValue } from "@posthog/ui/features/auth/store";
import { useCurrentUser } from "@posthog/ui/features/auth/useCurrentUser";
import {
  ownedProjectFeeds,
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
    () => ownedProjectFeeds(feeds, projectId, ownerId),
    [feeds, ownerId, projectId],
  );
}

export function useProjectTaskFeed(feedId: string): TaskFeed | undefined {
  const feeds = useProjectTaskFeeds();
  return feeds.find((feed) => feed.id === feedId);
}

export function useProjectTaskFeedsReady(): boolean {
  const client = useOptionalAuthenticatedClient();
  const { isLoading } = useCurrentUser({ client });
  const hasHydrated = useTaskFeedsStore((state) => state.hasHydrated);
  return hasHydrated && !isLoading;
}
