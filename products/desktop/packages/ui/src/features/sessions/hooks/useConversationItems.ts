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

export const MAX_CACHED_CONVERSATIONS = 8;

function createCache(): Cache {
  return {
    impl: createIncrementalConversationBuilder(),
    events: null,
    pending: null,
    debug: undefined,
    result: null,
  };
}

/**
 * Builds conversation items incrementally — each event is parsed once and
 * completed turns are reused by reference, so a streamed token costs work
 * proportional to the active turn rather than the whole thread. Builders and
 * results are kept per conversation in an LRU-bounded map, so switching tasks
 * and back returns the cached result instead of re-parsing the whole thread.
 * Results are memoized on the (events, pending, debug) triple so unrelated
 * re-renders don't re-derive.
 */
export function useConversationItems(
  conversationKey: string,
  events: AcpMessage[],
  isPromptPending: boolean | null,
  options?: BuildConversationOptions,
): BuildResult {
  const cachesRef = useRef<Map<string, Cache> | null>(null);
  if (!cachesRef.current) {
    cachesRef.current = new Map();
  }
  const caches = cachesRef.current;

  let cache = caches.get(conversationKey);
  if (cache) {
    caches.delete(conversationKey);
  } else {
    cache = createCache();
  }
  caches.set(conversationKey, cache);
  if (caches.size > MAX_CACHED_CONVERSATIONS) {
    const oldest = caches.keys().next().value;
    if (oldest !== undefined) {
      caches.delete(oldest);
    }
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
