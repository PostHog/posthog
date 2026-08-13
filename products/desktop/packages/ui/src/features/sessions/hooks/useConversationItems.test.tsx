import type { AcpMessage } from "@posthog/shared";
import { renderHook } from "@testing-library/react";
import { StrictMode } from "react";
import { beforeEach, describe, expect, it } from "vitest";
import {
  clearConversationItemCaches,
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
  conversationKey: string | undefined;
  events: AcpMessage[];
}

function renderConversationItems(initialProps: HookProps) {
  return renderHook(
    ({ conversationKey, events }: HookProps) =>
      useConversationItems(conversationKey, events, false),
    { initialProps, wrapper: StrictMode },
  );
}

describe("useConversationItems", () => {
  beforeEach(() => {
    clearConversationItemCaches();
  });

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

  it("shares one build between instances of the same conversation", () => {
    const events = conversation("a");
    const first = renderConversationItems({
      conversationKey: "a",
      events,
    });
    const second = renderConversationItems({
      conversationKey: "a",
      events,
    });

    expect(second.result.current).toBe(first.result.current);

    first.unmount();
    second.unmount();
  });

  it("keeps un-keyed instances isolated from each other", () => {
    const events = conversation("a");
    const first = renderConversationItems({
      conversationKey: undefined,
      events,
    });
    const second = renderConversationItems({
      conversationKey: undefined,
      events,
    });

    expect(second.result.current).not.toBe(first.result.current);

    first.unmount();
    second.unmount();
  });

  it("keeps a recently used conversation past the cap", () => {
    const eventsA = conversation("a");
    const { result, rerender } = renderConversationItems({
      conversationKey: "a",
      events: eventsA,
    });
    const builtForA = result.current;

    for (let i = 0; i < MAX_CACHED_CONVERSATIONS - 1; i++) {
      rerender({ conversationKey: `other-${i}`, events: conversation(`${i}`) });
    }
    rerender({ conversationKey: "a", events: eventsA });
    expect(result.current).toBe(builtForA);

    rerender({ conversationKey: "extra-1", events: conversation("x1") });
    rerender({ conversationKey: "extra-2", events: conversation("x2") });
    rerender({ conversationKey: "a", events: eventsA });
    expect(result.current).toBe(builtForA);
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
