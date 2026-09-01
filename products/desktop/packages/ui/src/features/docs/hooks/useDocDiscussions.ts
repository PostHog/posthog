import {
  type DocSchemas,
  listDiscussions,
  replyToDiscussion,
  setDiscussionResolved,
  startDiscussion,
} from "@posthog/api-client/docs";
import { AUTH_SCOPED_QUERY_META } from "@posthog/ui/features/auth/useCurrentUser";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { docsKeys } from "./docsKeys";
import { useDocsClient } from "./useDocsClient";

/**
 * Discussions on one doc. The doc's live stream says when a thread changed, so
 * these never poll: the panel refetches on that signal.
 */
export function useDocDiscussions(docId: string | null) {
  const docsClient = useDocsClient();
  return useQuery({
    queryKey: docsKeys.discussions(docsClient?.projectId ?? null, docId ?? ""),
    queryFn: async (): Promise<DocSchemas.DiscussionThread[]> => {
      if (!docsClient || !docId) throw new Error("No doc to load");
      return listDiscussions(docsClient.client, docsClient.projectId, docId);
    },
    enabled: !!docsClient && !!docId,
    staleTime: 30_000,
    meta: AUTH_SCOPED_QUERY_META,
  });
}

export function useDiscussionMutations(docId: string | null) {
  const docsClient = useDocsClient();
  const queryClient = useQueryClient();
  const key = docsKeys.discussions(docsClient?.projectId ?? null, docId ?? "");
  const refresh = () => {
    void queryClient.invalidateQueries({ queryKey: key });
  };

  const start = useMutation({
    mutationFn: async (input: {
      content: string;
      anchorKey: string;
      anchorText: string;
    }): Promise<DocSchemas.DiscussionThread> => {
      if (!docsClient || !docId) throw new Error("No doc to discuss");
      return startDiscussion(docsClient.client, docsClient.projectId, docId, {
        content: input.content,
        anchor_key: input.anchorKey,
        anchor_text: input.anchorText,
      });
    },
    onSuccess: refresh,
  });

  const reply = useMutation({
    mutationFn: async (input: {
      threadId: string;
      content: string;
    }): Promise<DocSchemas.DiscussionThread> => {
      if (!docsClient || !docId) throw new Error("No doc to discuss");
      return replyToDiscussion(
        docsClient.client,
        docsClient.projectId,
        docId,
        input.threadId,
        input.content,
      );
    },
    onSuccess: refresh,
  });

  const setResolved = useMutation({
    mutationFn: async (input: {
      threadId: string;
      resolved: boolean;
    }): Promise<DocSchemas.DiscussionThread> => {
      if (!docsClient || !docId) throw new Error("No doc to discuss");
      return setDiscussionResolved(
        docsClient.client,
        docsClient.projectId,
        docId,
        input.threadId,
        input.resolved,
      );
    },
    onSuccess: refresh,
  });

  return { start, reply, setResolved, refresh };
}
