import type { AgentConversationEvent } from "@posthog/shared";
import type { BuildResult } from "@posthog/ui/features/sessions/components/buildConversationItems";
import { createIncrementalAgentConversationBuilder } from "@posthog/ui/features/sessions/components/incrementalConversationItems";
import { useRef } from "react";

export function useAgentConversationItems(
  events: AgentConversationEvent[],
  isPromptPending: boolean | null,
  historyVersion: number,
  currentRunId?: string,
): BuildResult {
  const ref = useRef<{
    builder: ReturnType<typeof createIncrementalAgentConversationBuilder>;
    events: AgentConversationEvent[] | null;
    pending: boolean | null;
    version: number;
    currentRunId: string | undefined;
    result: BuildResult | null;
  } | null>(null);
  if (!ref.current) {
    ref.current = {
      builder: createIncrementalAgentConversationBuilder(),
      events: null,
      pending: null,
      version: historyVersion,
      currentRunId: undefined,
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
    cache.pending !== isPromptPending ||
    cache.currentRunId !== currentRunId
  ) {
    cache.result = cache.builder.update(events, isPromptPending, {
      currentRunId,
    });
    cache.events = events;
    cache.pending = isPromptPending;
    cache.currentRunId = currentRunId;
    cache.version = historyVersion;
  }
  return cache.result;
}
