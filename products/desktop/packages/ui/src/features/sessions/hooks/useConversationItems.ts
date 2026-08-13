import { MAX_CONNECTED_SESSIONS } from "@posthog/core/sessions/sessionEviction";
import type { AcpMessage } from "@posthog/shared";
import type {
  BuildConversationOptions,
  BuildResult,
} from "@posthog/ui/features/sessions/components/buildConversationItems";
import { createIncrementalConversationBuilder } from "@posthog/ui/features/sessions/components/incrementalConversationItems";
import { useRef } from "react";

interface Cache {
  impl: ReturnType<typeof createIncrementalConversationBuilder>;
  events: AcpMessage[] | null;
  pending: boolean | null;
  debug: boolean | undefined;
  result: BuildResult | null;
}

export const MAX_CACHED_CONVERSATIONS = MAX_CONNECTED_SESSIONS;

const sharedCaches = new Map<string, Cache>();

export function clearConversationItemCaches(): void {
  sharedCaches.clear();
}

function createCache(): Cache {
  return {
    impl: createIncrementalConversationBuilder(),
    events: null,
    pending: null,
    debug: undefined,
    result: null,
  };
}

function sharedCacheFor(conversationKey: string): Cache {
  let cache = sharedCaches.get(conversationKey);
  if (cache) {
    sharedCaches.delete(conversationKey);
  } else {
    cache = createCache();
  }
  sharedCaches.set(conversationKey, cache);
  if (sharedCaches.size > MAX_CACHED_CONVERSATIONS) {
    const oldest = sharedCaches.keys().next().value;
    if (oldest !== undefined) {
      sharedCaches.delete(oldest);
    }
  }
  return cache;
}

/**
 * Builds conversation items incrementally — each event is parsed once and
 * completed turns are reused by reference, so a streamed token costs work
 * proportional to the active turn rather than the whole thread. Keyed builders
 * live in a shared LRU, so every consumer of one conversation reuses one
 * build and revisiting a recent conversation skips the re-parse; un-keyed
 * callers get a private single-slot cache. Results are memoized on the
 * (events, pending, debug) triple so unrelated re-renders don't re-derive.
 */
export function useConversationItems(
  conversationKey: string | undefined,
  events: AcpMessage[],
  isPromptPending: boolean | null,
  options?: BuildConversationOptions,
): BuildResult {
  const localCacheRef = useRef<Cache | null>(null);

  let cache: Cache;
  if (conversationKey) {
    cache = sharedCacheFor(conversationKey);
  } else {
    if (!localCacheRef.current) {
      localCacheRef.current = createCache();
    }
    cache = localCacheRef.current;
  }

  const debug = options?.showDebugLogs;

  if (
    cache.result &&
    cache.events === events &&
    cache.pending === isPromptPending &&
    cache.debug === debug
  ) {
    return cache.result;
  }

  const result = cache.impl.update(events, isPromptPending, options);
  cache.events = events;
  cache.pending = isPromptPending;
  cache.debug = debug;
  cache.result = result;
  return result;
}
