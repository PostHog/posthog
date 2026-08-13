import type { AcpMessage } from "@posthog/shared";
import type {
  BuildConversationOptions,
  BuildResult,
} from "@posthog/ui/features/sessions/components/buildConversationItems";
import {
  type ConversationBuildCache,
  type ConversationPersistKey,
  createEmptyBuildCache,
  getConversationBuildCache,
} from "@posthog/ui/features/sessions/hooks/conversationDerivedCache";
import { useRef } from "react";

/**
 * Builds conversation items incrementally: each event is parsed once and
 * completed turns are reused by reference, so a streamed token costs work
 * proportional to the active turn rather than the whole thread. Results are
 * memoized on the (events, pending, debug) triple so unrelated re-renders
 * don't re-derive.
 *
 * Without a `persistKey` (or without a taskId in it) the builder lives in a
 * ref and dies with the component, so every remount re-parses the full
 * transcript. With one, it lives in a module-level cache instead, making
 * re-opening a task cheap. The mounted component pins its cache entry in a
 * ref: LRU eviction must never force a still-mounted view (e.g. one cell of a
 * grid larger than the cache) onto a fresh builder.
 */
export function useConversationItems(
  events: AcpMessage[],
  isPromptPending: boolean | null,
  options?: BuildConversationOptions,
  persistKey?: ConversationPersistKey,
): BuildResult {
  const pinnedRef = useRef<{
    key: string;
    cache: ConversationBuildCache;
  } | null>(null);
  const localRef = useRef<ConversationBuildCache | null>(null);
  let cache: ConversationBuildCache;
  // Empty transcripts are trivial to rebuild; keeping them out of the cache
  // stops surfaces that render before events arrive (or never get any) from
  // occupying its slots.
  if (persistKey?.taskId !== undefined && events.length > 0) {
    const pinKey = `${persistKey.scope} ${persistKey.taskId}`;
    if (pinnedRef.current?.key !== pinKey) {
      pinnedRef.current = {
        key: pinKey,
        cache: getConversationBuildCache({
          scope: persistKey.scope,
          taskId: persistKey.taskId,
        }),
      };
    }
    cache = pinnedRef.current.cache;
  } else {
    localRef.current ??= createEmptyBuildCache();
    cache = localRef.current;
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
