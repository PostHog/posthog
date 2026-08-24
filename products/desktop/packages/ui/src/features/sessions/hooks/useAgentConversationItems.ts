import type { AgentConversationEvent } from "@posthog/shared";
import {
  type BuildResult,
  buildAgentConversationItems,
} from "@posthog/ui/features/sessions/components/buildConversationItems";
import { useMemo } from "react";

export function useAgentConversationItems(
  events: AgentConversationEvent[],
  isPromptPending: boolean | null,
): BuildResult {
  return useMemo(
    () => buildAgentConversationItems(events, isPromptPending),
    [events, isPromptPending],
  );
}
