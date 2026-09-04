import type { ConversationItem } from "@posthog/ui/features/sessions/components/buildConversationItems";
import type { ToolGroupItem } from "@posthog/ui/features/sessions/components/chat-thread/ToolGroup";
import { describe, expect, it } from "vitest";
import { buildTurnCopyText, buildTurnCopyTextCached } from "./turnCopyText";

function userMessage(id: string, content: string): ConversationItem {
  return { type: "user_message", id, content, timestamp: 0 };
}

function agentText(id: string, text: string): ConversationItem {
  return {
    type: "session_update",
    id,
    update: {
      sessionUpdate: "agent_message_chunk",
      content: { type: "text", text },
    },
    turnContext: {
      toolCalls: new Map(),
      childItems: new Map(),
      turnCancelled: false,
      turnComplete: true,
    },
  } as ConversationItem;
}

function toolCall(id: string): ConversationItem {
  return {
    type: "session_update",
    id,
    update: {
      sessionUpdate: "tool_call",
      toolCallId: id,
      title: "Read file",
      status: "completed",
    },
    turnContext: {
      toolCalls: new Map(),
      childItems: new Map(),
      turnCancelled: false,
      turnComplete: true,
    },
  } as ConversationItem;
}

function toolGroup(id: string): ToolGroupItem {
  return { type: "tool_group", id, tools: [] } as unknown as ToolGroupItem;
}

describe("buildTurnCopyText", () => {
  it("joins the rows' prose in order", () => {
    const text = buildTurnCopyText([
      agentText("a1", "first paragraph"),
      agentText("a2", "second paragraph"),
    ]);

    expect(text).toBe("first paragraph\n\nsecond paragraph");
  });

  it("skips user prompts, tool calls, tool groups and other non-agent rows", () => {
    const text = buildTurnCopyText([
      userMessage("u1", "do the thing"),
      toolCall("t1"),
      toolGroup("g1"),
      agentText("a1", "done"),
    ]);

    expect(text).toBe("done");
  });

  it.each([
    ["no items", [] as ConversationItem[]],
    ["tools only", [toolCall("t1"), toolGroup("g1")]],
    ["blank agent prose", [userMessage("u1", "prompt"), agentText("a1", "\n")]],
  ])("returns null when there is nothing to copy: %s", (_label, items) => {
    expect(buildTurnCopyText(items)).toBeNull();
  });
});

describe("buildTurnCopyTextCached", () => {
  it("matches the uncached result across rebuilt container arrays", () => {
    const items = [agentText("a1", "first"), agentText("a2", "second")];

    expect(buildTurnCopyTextCached([...items])).toBe(
      buildTurnCopyText([...items]),
    );
    expect(buildTurnCopyTextCached([...items])).toBe("first\n\nsecond");
  });

  it("recomputes when the turn gains an item", () => {
    const first = agentText("a1", "first");
    expect(buildTurnCopyTextCached([first])).toBe("first");

    expect(buildTurnCopyTextCached([first, agentText("a2", "second")])).toBe(
      "first\n\nsecond",
    );
  });

  it("returns null for an empty turn without caching", () => {
    expect(buildTurnCopyTextCached([])).toBeNull();
  });
});
