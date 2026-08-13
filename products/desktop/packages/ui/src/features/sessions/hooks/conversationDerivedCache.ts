import type { AcpMessage } from "@posthog/shared";
import type { BuildResult } from "@posthog/ui/features/sessions/components/buildConversationItems";
import { createIncrementalConversationBuilder } from "@posthog/ui/features/sessions/components/incrementalConversationItems";
import { createIncrementalThreadGrouper } from "@posthog/ui/features/sessions/components/new-thread/incrementalThreadGrouping";
import { useSessionStore } from "@posthog/ui/features/sessions/sessionStore";
import { LRUCache } from "lru-cache";
import { useRef } from "react";

export interface ConversationBuildCache {
  impl: ReturnType<typeof createIncrementalConversationBuilder>;
  events: AcpMessage[] | null;
  pending: boolean | null;
  debug: boolean | undefined;
  result: BuildResult | null;
}

type ThreadGrouper = ReturnType<typeof createIncrementalThreadGrouper>;

/**
 * Call-site namespace. Surfaces that feed different inputs for the same task
 * must not share builder state, or they would invalidate each other on every
 * render. Closed union on purpose: a colliding scope string would silently
 * share one builder between unrelated surfaces.
 */
export type ConversationCacheScope = "conversation-view" | "chat-thread";

export interface ConversationCacheKey {
  scope: ConversationCacheScope;
  taskId: string;
}

export interface ConversationPersistKey {
  scope: ConversationCacheScope;
  /** Surfaces rendering without a task fall back to per-component state. */
  taskId: string | undefined;
}

interface Entry {
  /**
   * The session run whose store-resident events the cached state was built
   * from. Entries are swept when that run's events leave the store. Entries
   * whose events never came from the store stay null (archive surfaces) and
   * are reclaimed by the LRU cap and TTL instead, or unrelated store commits
   * would sweep them and force a rebuild on every render.
   */
  taskRunId: string | null;
  build?: ConversationBuildCache;
  grouper?: ThreadGrouper;
}

/**
 * Re-opening a task unmounts and remounts its whole view tree, so
 * per-component caches die with it and every click re-parses the full
 * transcript (seconds of main-thread work for large sessions). This
 * module-level cache keeps the incremental builder state alive across mounts.
 *
 * Bounds: at most MAX_CACHED_TASKS entries per scope, and entries not touched
 * for CACHE_TTL_MS expire on their own (the store sweep below cannot see
 * surfaces whose transcripts never enter the session store). Mounted
 * components pin their entry in a ref (see useConversationItems), so LRU
 * eviction only ever costs an unmounted task its warm re-open.
 */
export const MAX_CACHED_TASKS = 8;
const CACHE_TTL_MS = 30 * 60_000;

const scopes = new Map<ConversationCacheScope, LRUCache<string, Entry>>();

export function createEmptyBuildCache(): ConversationBuildCache {
  return {
    impl: createIncrementalConversationBuilder(),
    events: null,
    pending: null,
    debug: undefined,
    result: null,
  };
}

export function getConversationBuildCache(
  key: ConversationCacheKey,
): ConversationBuildCache {
  const entry = getEntry(key);
  entry.build ??= createEmptyBuildCache();
  return entry.build;
}

export function getPersistentThreadGrouper(
  key: ConversationCacheKey,
): ThreadGrouper {
  const entry = getEntry(key);
  entry.grouper ??= createIncrementalThreadGrouper();
  return entry.grouper;
}

/**
 * The thread grouper counterpart of useConversationItems' persistence:
 * persistent (and pinned for the mounted lifetime) when a taskId is present,
 * per-component otherwise.
 */
export function usePersistentThreadGrouper(
  scope: ConversationCacheScope,
  taskId: string | undefined,
): ThreadGrouper {
  const pinnedRef = useRef<{ key: string; grouper: ThreadGrouper } | null>(
    null,
  );
  const localRef = useRef<ThreadGrouper | null>(null);
  if (taskId !== undefined) {
    const pinKey = `${scope} ${taskId}`;
    if (pinnedRef.current?.key !== pinKey) {
      pinnedRef.current = {
        key: pinKey,
        grouper: getPersistentThreadGrouper({ scope, taskId }),
      };
    }
    return pinnedRef.current.grouper;
  }
  localRef.current ??= createIncrementalThreadGrouper();
  return localRef.current;
}

function getEntry(key: ConversationCacheKey): Entry {
  let scopeCache = scopes.get(key.scope);
  if (!scopeCache) {
    scopeCache = new LRUCache({
      max: MAX_CACHED_TASKS,
      ttl: CACHE_TTL_MS,
      ttlAutopurge: true,
      updateAgeOnGet: true,
    });
    scopes.set(key.scope, scopeCache);
  }
  let entry = scopeCache.get(key.taskId);
  if (!entry) {
    entry = { taskRunId: null };
    scopeCache.set(key.taskId, entry);
  }
  // Latch to the run currently backing the task, but only once its events are
  // store-resident: those are what the cached state is built from, so that
  // exact run's eviction is the signal to drop the entry.
  const state = useSessionStore.getState();
  const taskRunId = state.taskIdIndex[key.taskId];
  if (taskRunId !== undefined) {
    const session = state.sessions[taskRunId];
    if (session !== undefined && session.events.length > 0) {
      entry.taskRunId = taskRunId;
    }
  }
  return entry;
}

// When the residency system evicts a backgrounded session's events (or the
// session is torn down), drop its derived caches too: they reference the
// evicted events, and keeping them would defeat the memory reclaim.
useSessionStore.subscribe((state, prevState) => {
  if (state.sessions === prevState.sessions) return;
  for (const scopeCache of scopes.values()) {
    // Collect first: deleting while iterating an LRUCache is not guaranteed safe.
    const evicted: string[] = [];
    for (const [taskId, entry] of scopeCache.entries()) {
      if (entry.taskRunId === null) continue;
      const session = state.sessions[entry.taskRunId];
      if (!session || session.events.length === 0) {
        evicted.push(taskId);
      }
    }
    for (const taskId of evicted) {
      scopeCache.delete(taskId);
    }
  }
});
