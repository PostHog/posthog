import type { AgentConversationEvent } from "@posthog/shared";
import { buildAgentConversationItems } from "@posthog/ui/features/sessions/components/buildConversationItems";
import { renderHook } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { useAgentConversationItems } from "./useAgentConversationItems";

describe("useAgentConversationItems", () => {
  it("rebuilds when a server acknowledgement replaces a message inside the consumed prefix", () => {
    let events: AgentConversationEvent[] = [
      {
        type: "user_message",
        id: "first",
        timestamp: 1,
        content: [{ type: "text", text: "First" }],
      },
      { type: "turn_completed", timestamp: 2 },
      {
        type: "user_message",
        id: "optimistic",
        timestamp: 3,
        content: [{ type: "text", text: "Draft" }],
      },
      {
        type: "assistant_message_chunk",
        timestamp: 4,
        content: { type: "text", text: "Response" },
      },
    ];
    let version = 0;
    const { result, rerender } = renderHook(() =>
      useAgentConversationItems(events, true, version),
    );
    const previous = result.current;
    rerender();
    expect(result.current).toBe(previous);
    events = [...events];
    events[2] = {
      type: "user_message",
      id: "optimistic",
      timestamp: 3,
      content: [{ type: "text", text: "Confirmed" }],
    };
    version++;
    rerender();
    expect(result.current).toEqual(buildAgentConversationItems(events, true));
  });
});
