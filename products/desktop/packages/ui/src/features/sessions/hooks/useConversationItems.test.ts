import { renderHook } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const warn = vi.hoisted(() => vi.fn());
vi.mock("@posthog/ui/shell/logger", () => ({
  logger: {
    scope: () => ({ error: vi.fn(), warn, info: vi.fn(), debug: vi.fn() }),
  },
}));

import type { AcpMessage } from "@posthog/shared";
import { useConversationItems } from "./useConversationItems";

let ts = 1;
function update(sessionUpdate: string, extra: Record<string, unknown> = {}) {
  return {
    type: "acp_message",
    ts: ts++,
    message: {
      jsonrpc: "2.0",
      method: "session/update",
      params: { sessionId: "run-1", update: { sessionUpdate, ...extra } },
    },
  } as unknown as AcpMessage;
}

const chunk = (text: string) =>
  update("agent_message_chunk", { content: { type: "text", text } });
const usage = () => update("usage_update", { used: 1, size: 100 });

describe("useConversationItems", () => {
  beforeEach(() => warn.mockClear());

  it("logs once when many events arrive without changing what is shown", () => {
    let events: AcpMessage[] = [chunk("hello")];
    const { rerender } = renderHook(() => useConversationItems(events, true));

    for (let i = 0; i < 60; i++) {
      events = [...events, usage()];
      rerender();
    }

    expect(warn).toHaveBeenCalledTimes(1);
    expect(warn).toHaveBeenCalledWith(
      "Transcript received events without a visible change",
      expect.objectContaining({ itemCount: 1, isPromptPending: true }),
    );
  });

  it("stays quiet while streamed text keeps growing the last item", () => {
    let events: AcpMessage[] = [chunk("a")];
    const { rerender } = renderHook(() => useConversationItems(events, true));

    for (let i = 0; i < 80; i++) {
      events = [...events, chunk("b")];
      rerender();
    }

    expect(warn).not.toHaveBeenCalled();
  });
});
