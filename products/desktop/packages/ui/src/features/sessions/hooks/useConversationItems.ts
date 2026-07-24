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

/**
 * Builds conversation items incrementally — each event is parsed once and
 * completed turns are reused by reference, so a streamed token costs work
 * proportional to the active turn rather than the whole thread. The persistent
 * builder lives in a ref; results are memoized on the (events, pending, debug)
 * triple so unrelated re-renders don't re-derive.
 */
export function useConversationItems(
  events: AcpMessage[],
  isPromptPending: boolean | null,
  options?: BuildConversationOptions,
): BuildResult {
  const ref = useRef<Cache | null>(null);
  if (!ref.current) {
    ref.current = {
      impl: createIncrementalConversationBuilder(),
      events: null,
      pending: null,
      debug: undefined,
      result: null,
    };
  }
  const cache = ref.current;
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
