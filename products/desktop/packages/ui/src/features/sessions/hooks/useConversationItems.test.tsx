import type { AcpMessage } from "@posthog/shared";
import { renderHook } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import {
  type ConversationPersistKey,
  getConversationBuildCache,
  MAX_CACHED_TASKS,
} from "./conversationDerivedCache";
import { useConversationItems } from "./useConversationItems";

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

function transcript(): AcpMessage[] {
  return [
    userPromptMsg(1, 1, "first prompt"),
    promptResponseMsg(2, 1),
    userPromptMsg(3, 2, "second prompt"),
  ];
}

describe("useConversationItems persistence", () => {
  it("returns the identical result after a remount with a persist key", () => {
    const events = transcript();
    const key: ConversationPersistKey = {
      scope: "chat-thread",
      taskId: "idle-remount",
    };

    const first = renderHook(() =>
      useConversationItems(events, false, undefined, key),
    );
    const firstResult = first.result.current;
    first.unmount();

    const second = renderHook(() =>
      useConversationItems(events, false, undefined, key),
    );
    expect(second.result.current).toBe(firstResult);
  });

  it("reuses completed turn items across a remount while streaming", () => {
    const events = transcript();
    const key: ConversationPersistKey = {
      scope: "chat-thread",
      taskId: "streaming-remount",
    };

    const first = renderHook(() =>
      useConversationItems(events, true, undefined, key),
    );
    const firstItems = first.result.current.items;
    first.unmount();

    // Streaming appends preserve element identity (immer structural sharing);
    // a surviving builder must take the append fast path, not rebuild.
    const appended = [...events, promptResponseMsg(4, 2)];
    const second = renderHook(() =>
      useConversationItems(appended, true, undefined, key),
    );
    expect(second.result.current.items[0]).toBe(firstItems[0]);
  });

  it("keeps a mounted view on its builder when the LRU evicts its entry", () => {
    const events = transcript();
    const key: ConversationPersistKey = {
      scope: "chat-thread",
      taskId: "pinned-mounted",
    };

    const hook = renderHook(
      ({ evs }: { evs: AcpMessage[] }) =>
        useConversationItems(evs, true, undefined, key),
      { initialProps: { evs: events } },
    );
    const firstItems = hook.result.current.items;

    // Push the mounted entry out of the scope's LRU (a grid can mount more
    // views than the cache holds); the pinned builder must keep streaming
    // incrementally instead of rebuilding from scratch every render.
    for (let i = 0; i <= MAX_CACHED_TASKS; i++) {
      getConversationBuildCache({
        scope: "chat-thread",
        taskId: `pin-filler-${i}`,
      });
    }

    const appended = [...events, promptResponseMsg(4, 2)];
    hook.rerender({ evs: appended });
    expect(hook.result.current.items[0]).toBe(firstItems[0]);
  });

  it("rebuilds from scratch on remount without a persist key", () => {
    const events = transcript();

    const first = renderHook(() => useConversationItems(events, false));
    const firstItems = first.result.current.items;
    first.unmount();

    const second = renderHook(() => useConversationItems(events, false));
    expect(second.result.current.items[0]).not.toBe(firstItems[0]);
  });

  it("treats a persist key without a taskId as non-persistent", () => {
    const events = transcript();
    const key: ConversationPersistKey = {
      scope: "chat-thread",
      taskId: undefined,
    };

    const first = renderHook(() =>
      useConversationItems(events, false, undefined, key),
    );
    const firstItems = first.result.current.items;
    first.unmount();

    const second = renderHook(() =>
      useConversationItems(events, false, undefined, key),
    );
    expect(second.result.current.items[0]).not.toBe(firstItems[0]);
  });
});
