import type { AgentConversationEvent } from "@posthog/shared";
import type { BuildResult } from "@posthog/ui/features/sessions/components/buildConversationItems";
import { createIncrementalAgentConversationBuilder } from "@posthog/ui/features/sessions/components/incrementalConversationItems";
import { useRef } from "react";

export function useAgentConversationItems(
  events: AgentConversationEvent[],
  isPromptPending: boolean | null,
  historyVersion: number,
): BuildResult {
  const ref = useRef<{
    builder: ReturnType<typeof createIncrementalAgentConversationBuilder>;
    events: AgentConversationEvent[] | null;
    pending: boolean | null;
    version: number;
    result: BuildResult | null;
  } | null>(null);
  if (!ref.current) {
    ref.current = {
      builder: createIncrementalAgentConversationBuilder(),
      events: null,
      pending: null,
      version: historyVersion,
      result: null,
    };
  }
  const cache = ref.current;
  // A server acknowledgement can replace an optimistic message inside the prefix.
  if (cache.version !== historyVersion) {
    cache.builder.reset();
    cache.result = null;
  }
  if (
    !cache.result ||
    cache.events !== events ||
    cache.pending !== isPromptPending
  ) {
    cache.result = cache.builder.update(events, isPromptPending);
    cache.events = events;
    cache.pending = isPromptPending;
    cache.version = historyVersion;
  }
  return cache.result;
}
