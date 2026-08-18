import type { CommentEmoji } from "@posthog/api-client/posthog-client";
import {
  getAuthIdentity,
  useAuthStateValue,
} from "@posthog/ui/features/auth/store";
import { useAuthenticatedQuery } from "@posthog/ui/hooks/useAuthenticatedQuery";
import type { UseQueryResult } from "@tanstack/react-query";

export function useCommentEmojis(): UseQueryResult<CommentEmoji[], Error> {
  const authIdentity = useAuthStateValue(getAuthIdentity);
  return useAuthenticatedQuery(
    ["comment-emojis", authIdentity],
    (client) => client.getCommentEmojis(),
    { staleTime: 60 * 60 * 1_000, retry: false },
  );
}
