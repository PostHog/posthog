import { requestErrorStatus } from "@posthog/api-client/fetcher";
import type {
  ContextWikiPage,
  ContextWikiHealthReport,
  ContextWikiTree,
} from "@posthog/api-client/posthog-client";
import { useAuthenticatedMutation } from "@posthog/ui/hooks/useAuthenticatedMutation";
import { useAuthenticatedQuery } from "@posthog/ui/hooks/useAuthenticatedQuery";
import { useQueryClient } from "@tanstack/react-query";

export const CONTEXT_WIKI_TREE_KEY = ["context-wiki", "tree"] as const;
export const CONTEXT_WIKI_PAGE_KEY = (path: string) =>
  ["context-wiki", "page", path] as const;
export const CONTEXT_WIKI_REPORT_KEY = ["context-wiki", "report"] as const;

/** `null` data means the wiki was never enabled for this organization (404). */
export function useContextWikiTree() {
  return useAuthenticatedQuery<ContextWikiTree | null>(
    CONTEXT_WIKI_TREE_KEY,
    (client) => client.getContextWikiTree(),
    // Agents land wiki commits in the background (dream runs, task edits), so
    // a mounted explorer revalidates rather than trusting a session-old tree.
    { staleTime: 30_000, refetchOnMount: "always" },
  );
}

export function useContextWikiPage(path: string) {
  return useAuthenticatedQuery<ContextWikiPage | null>(
    CONTEXT_WIKI_PAGE_KEY(path),
    (client) => client.getContextWikiPage(path),
    // The pane remounts per selection, so revisits inside this window render
    // from cache; a stale-head save still fails safe via the 409 conflict.
    { staleTime: 30_000 },
  );
}

export function useContextWikiHealthReport() {
  return useAuthenticatedQuery<ContextWikiHealthReport | null>(
    CONTEXT_WIKI_REPORT_KEY,
    (client) => client.getContextWikiHealthReport(),
    { staleTime: 30_000, refetchOnMount: "always" },
  );
}

// How many times a lock-busy write is retried before the 429 surfaces.
const WIKI_WRITE_MAX_RETRIES = 3;

/**
 * A 429 means the org's wiki writer lock is busy (an agent is landing a
 * commit). Retrying with the same base head is safe; anything else — a 409
 * conflict, a 400 lint rejection, a network error — must fall through to the
 * caller's conflict/lint handling rather than being retried.
 */
export function shouldRetryWikiWrite(
  failureCount: number,
  error: unknown,
): boolean {
  return (
    failureCount < WIKI_WRITE_MAX_RETRIES && requestErrorStatus(error) === 429
  );
}

// Backoff between lock-busy retries: 400ms, 800ms, then 1200ms.
export function wikiWriteRetryDelay(failureCount: number): number {
  return 400 * (failureCount + 1);
}

export function useContextWikiPageMutation() {
  const queryClient = useQueryClient();
  return useAuthenticatedMutation<
    { head_sha: string },
    Error,
    { path: string; content: string; baseHead: string }
  >((client, input) => client.putContextWikiPage(input), {
    retry: shouldRetryWikiWrite,
    retryDelay: wikiWriteRetryDelay,
    onSuccess: (result, input) => {
      // The PUT echoes everything the caches need, so write them in place
      // instead of refetching content the client just uploaded.
      queryClient.setQueryData<ContextWikiPage>(
        CONTEXT_WIKI_PAGE_KEY(input.path),
        { path: input.path, content: input.content, head_sha: result.head_sha },
      );
      queryClient.setQueryData<ContextWikiTree | null>(
        CONTEXT_WIKI_TREE_KEY,
        (tree) => (tree ? { ...tree, head_sha: result.head_sha } : tree),
      );
    },
  });
}

export function useEnableContextWiki() {
  const queryClient = useQueryClient();
  return useAuthenticatedMutation<{ head_sha: string }, Error, void>(
    (client) => client.enableContextWiki(),
    {
      onSuccess: () => {
        void queryClient.invalidateQueries({ queryKey: CONTEXT_WIKI_TREE_KEY });
      },
    },
  );
}
