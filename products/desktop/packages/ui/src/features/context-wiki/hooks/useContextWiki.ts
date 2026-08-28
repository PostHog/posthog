import { requestErrorStatus } from "@posthog/api-client/fetcher";
import {
  type ChannelContextWikiPage,
  type ContextWikiHealthReport,
  type ContextWikiPage,
  type ContextWikiTree,
  ContextWikiUnavailableError,
} from "@posthog/api-client/posthog-client";
import { useAuthenticatedMutation } from "@posthog/ui/hooks/useAuthenticatedMutation";
import { useAuthenticatedQuery } from "@posthog/ui/hooks/useAuthenticatedQuery";
import { useQueryClient } from "@tanstack/react-query";

export const CONTEXT_WIKI_TREE_KEY = ["context-wiki", "tree"] as const;
export const CONTEXT_WIKI_PAGE_KEY = (path: string) =>
  ["context-wiki", "page", path] as const;
export const CONTEXT_WIKI_REPORT_KEY = ["context-wiki", "report"] as const;
export const CHANNEL_CONTEXT_WIKI_PAGE_KEY = (channelId: string) =>
  ["context-wiki", "channel-page", channelId] as const;

export function useChannelContextWikiPage(channelId: string, enabled = true) {
  return useAuthenticatedQuery<ChannelContextWikiPage | null>(
    CHANNEL_CONTEXT_WIKI_PAGE_KEY(channelId),
    (client) => client.getChannelContextWikiPage(channelId),
    { enabled, staleTime: 30_000, refetchOnMount: "always" },
  );
}

/** What a task composer should do about this space's context. */
export interface ChannelWikiContext {
  /** The wiki page to point the agent at, when one resolved. */
  path?: string;
  /** Send the space's legacy CONTEXT.md instead. */
  useLegacy: boolean;
  /** Hold submission: the lookup is in flight or can still succeed. */
  blocked: boolean;
  /** The lookup failed but retrying can fix it, so offer that. */
  failed: boolean;
  /** Say the space context is not coming along; retrying will not help. */
  unavailable: boolean;
  retry: () => void;
}

/**
 * Splits a failed lookup by whether retrying can fix it, so a task is never
 * submitted with the space's context silently missing.
 *
 * A transient failure holds submission, because the context is probably one
 * retry away. A 403 never clears — the organization has a private project — so
 * holding submission there would lock those spaces out of creating tasks at
 * all; that case says so and lets the task through.
 */
export function channelWikiContextFrom(lookup: {
  enabled: boolean;
  data: ChannelContextWikiPage | null | undefined;
  error: unknown;
  isLoading: boolean;
}): Omit<ChannelWikiContext, "retry"> {
  const unavailable = lookup.error instanceof ContextWikiUnavailableError;
  const transientFailure = Boolean(lookup.error) && !unavailable;

  return {
    path: lookup.data?.path ?? undefined,
    // `null` settles it: this space has no wiki page. An error settles nothing.
    useLegacy: !lookup.enabled || (lookup.data === null && !lookup.error),
    blocked: lookup.enabled && (lookup.isLoading || transientFailure),
    failed: lookup.enabled && transientFailure,
    unavailable: lookup.enabled && unavailable,
  };
}

export function useChannelWikiContext(
  channelId: string,
  enabled: boolean,
): ChannelWikiContext {
  const wikiPage = useChannelContextWikiPage(channelId, enabled);
  return {
    ...channelWikiContextFrom({
      enabled,
      data: wikiPage.data,
      error: wikiPage.error,
      isLoading: wikiPage.isLoading,
    }),
    retry: () => void wikiPage.refetch(),
  };
}

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
        {
          path: input.path,
          content: input.content,
          head_sha: result.head_sha,
          updated_at: new Date().toISOString(),
        },
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
