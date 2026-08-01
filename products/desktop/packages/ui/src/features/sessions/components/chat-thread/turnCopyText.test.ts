import type { ConversationItem } from "@posthog/ui/features/sessions/components/buildConversationItems";
import type { ToolGroupItem } from "@posthog/ui/features/sessions/components/chat-thread/ToolGroup";
import { describe, expect, it } from "vitest";
import { buildTurnCopyText } from "./turnCopyText";

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

  it("skips tool calls, tool groups and other non-prose rows", () => {
    const text = buildTurnCopyText([
      userMessage("u1", "do the thing"),
      toolCall("t1"),
      toolGroup("g1"),
      agentText("a1", "done"),
    ]);

    expect(text).toBe("do the thing\n\ndone");
  });

  it.each([
    ["no items", [] as ConversationItem[]],
    ["tools only", [toolCall("t1"), toolGroup("g1")]],
    ["blank prose", [userMessage("u1", "   "), agentText("a1", "\n")]],
  ])("returns null when there is nothing to copy: %s", (_label, items) => {
    expect(buildTurnCopyText(items)).toBeNull();
  });
});
