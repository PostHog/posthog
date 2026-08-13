import type { AcpMessage } from "@posthog/shared";
import { renderHook } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import {
  MAX_CACHED_CONVERSATIONS,
  useConversationItems,
} from "./useConversationItems";

function userPromptMsg(ts: number, id: number, text: string): AcpMessage {
  return {
    type: "acp_message",
    ts,
    message: {
      jsonrpc: "2.0",
      id,
      method: "session/prompt",
      params: { prompt: [{ type: "text", text }] },
    },
  };
}

function promptResponseMsg(ts: number, id: number): AcpMessage {
  return {
    type: "acp_message",
    ts,
    message: { jsonrpc: "2.0", id, result: { stopReason: "end_turn" } },
  };
}

function conversation(text: string): AcpMessage[] {
  return [userPromptMsg(1, 1, text), promptResponseMsg(2, 1)];
}

interface HookProps {
  conversationKey: string;
  events: AcpMessage[];
}

function renderConversationItems(initialProps: HookProps) {
  return renderHook(
    ({ conversationKey, events }: HookProps) =>
      useConversationItems(conversationKey, events, false),
    { initialProps },
  );
}

describe("useConversationItems", () => {
  it("returns the cached result when switching back to a conversation", () => {
    const eventsA = conversation("a");
    const eventsB = conversation("b");
    const { result, rerender } = renderConversationItems({
      conversationKey: "a",
      events: eventsA,
    });
    const builtForA = result.current;
    expect(builtForA.items.length).toBeGreaterThan(0);

    rerender({ conversationKey: "b", events: eventsB });
    expect(result.current).not.toBe(builtForA);

    rerender({ conversationKey: "a", events: eventsA });
    expect(result.current).toBe(builtForA);
  });

  it("rebuilds when a conversation's events change identity", () => {
    const eventsA = conversation("a");
    const { result, rerender } = renderConversationItems({
      conversationKey: "a",
      events: eventsA,
    });
    const builtForA = result.current;

    rerender({ conversationKey: "a", events: [...eventsA] });
    expect(result.current).not.toBe(builtForA);
  });

  it("evicts the least recently used conversation past the cap", () => {
    const eventsA = conversation("a");
    const { result, rerender } = renderConversationItems({
      conversationKey: "a",
      events: eventsA,
    });
    const builtForA = result.current;

    for (let i = 0; i < MAX_CACHED_CONVERSATIONS; i++) {
      rerender({ conversationKey: `other-${i}`, events: conversation(`${i}`) });
    }

    rerender({ conversationKey: "a", events: eventsA });
    expect(result.current).not.toBe(builtForA);
  });
});
