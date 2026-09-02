import { useHostTRPC } from "@posthog/host-router/react";
import type { PrConversationComment } from "@posthog/shared";
import { useQueries } from "@tanstack/react-query";

type PrCommentsResult = {
  data?: PrConversationComment[] | null;
  isLoading: boolean;
  isError: boolean;
};

export function combinePrCommentResults(
  prUrls: string[],
  results: PrCommentsResult[],
): {
  byUrl: Array<[string, PrConversationComment[]]>;
  isLoading: boolean;
  isError: boolean;
} {
  const failed = results.filter(
    (result) => result.isError || result.data === null,
  ).length;
  return {
    byUrl: prUrls.map(
      (prUrl, index) =>
        [prUrl, results[index]?.data ?? []] as [
          string,
          PrConversationComment[],
        ],
    ),
    isLoading: results.some((result) => result.isLoading),
    isError: results.length > 0 && failed === results.length,
  };
}

/**
 * Conversation comments for several PRs at once. GitHub has no batch endpoint
 * for these, so this is one request per PR — fine for the handful a task
 * produces, and cached long enough that revisiting the pane is free.
 *
 * `byUrl` is a plain array of [url, comments] pairs rather than a Map so
 * react-query's structural sharing keeps its identity stable while the data is
 * unchanged; a Map would be a fresh object every render and defeat the memos
 * that read it.
 */
export function usePrCommentsForUrls(prUrls: string[]) {
  const trpc = useHostTRPC();
  return useQueries({
    queries: prUrls.map((prUrl) => ({
      ...trpc.git.getPrComments.queryOptions({ prUrl }),
      staleTime: 30_000,
      placeholderData: (prev: PrConversationComment[] | null | undefined) =>
        prev,
      retry: 1,
    })),
    combine: (results) => combinePrCommentResults(prUrls, results),
  });
}
