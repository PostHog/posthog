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
import { logger } from "@posthog/ui/shell/logger";
import { useRef } from "react";

const log = logger.scope("transcript");

/**
 * How many new events may arrive without changing what the thread shows
 * before that is logged. Streamed text grows the last item on every event, so
 * a healthy turn never gets close.
 */
const STALL_EVENT_THRESHOLD = 50;

/**
 * Cheap fingerprint of what the thread would show for a build result: item
 * count, the last item and how much of it there is. Streamed text, tool status
 * flips and plan entries all move it; a batch of events that leaves it
 * untouched is a transcript that looks frozen.
 */
function visibleSignature(result: BuildResult): string {
  const last = result.items[result.items.length - 1];
  if (!last) return `0|${result.completedToolCallCount}`;
  let detail = "";
  if (last.type === "session_update") {
    const update = last.update as {
      sessionUpdate: string;
      status?: unknown;
      content?: { text?: unknown };
      entries?: unknown;
    };
    const text =
      typeof update.content?.text === "string" ? update.content.text.length : 0;
    const entries = Array.isArray(update.entries) ? update.entries.length : "";
    detail = `${update.sessionUpdate}:${String(update.status ?? "")}:${text}:${entries}`;
  } else if (last.type === "user_message") {
    detail = `user:${last.content.length}`;
  }
  return `${result.items.length}|${last.id}|${detail}|${result.completedToolCallCount}`;
}

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
  noteVisibleChange(cache, events, isPromptPending, result);
  return result;
}

function noteVisibleChange(
  cache: ConversationBuildCache,
  events: AcpMessage[],
  isPromptPending: boolean | null,
  result: BuildResult,
): void {
  const visible = visibleSignature(result);
  if (visible !== cache.visible) {
    cache.visible = visible;
    cache.eventsAtLastVisibleChange = events.length;
    cache.stallLogged = false;
    return;
  }
  const unseen = events.length - cache.eventsAtLastVisibleChange;
  if (unseen < STALL_EVENT_THRESHOLD || cache.stallLogged) return;
  cache.stallLogged = true;
  const lastEvent = events[events.length - 1]?.message as
    | { method?: unknown }
    | undefined;
  log.warn("Transcript received events without a visible change", {
    eventCount: events.length,
    unseenEvents: unseen,
    itemCount: result.items.length,
    isPromptPending,
    lastEventMethod:
      typeof lastEvent?.method === "string" ? lastEvent.method : "response",
  });
}
