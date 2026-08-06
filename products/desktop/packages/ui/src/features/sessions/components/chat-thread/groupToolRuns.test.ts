import type { ConversationItem } from "@posthog/ui/features/sessions/components/buildConversationItems";
import { describe, expect, it } from "vitest";
import { groupToolRuns } from "./ChatThread";

function turnContext() {
  return {
    toolCalls: new Map(),
    childItems: new Map(),
    turnCancelled: false,
    turnComplete: true,
  };
}

function toolItem(id: string): ConversationItem {
  return {
    type: "session_update",
    id,
    update: {
      sessionUpdate: "tool_call",
      toolCallId: id,
      title: id,
      kind: "read",
      status: "completed",
    },
    turnContext: turnContext(),
  } as ConversationItem;
}

function thoughtItem(id: string): ConversationItem {
  return {
    type: "session_update",
    id,
    update: {
      sessionUpdate: "agent_thought_chunk",
      content: { type: "text", text: "Considering the next step" },
    },
    thoughtComplete: true,
    turnContext: turnContext(),
  } as ConversationItem;
}

describe("groupToolRuns", () => {
  it("keeps thoughts outside adjacent tool groups", () => {
    const grouped = groupToolRuns([
      toolItem("read-1"),
      toolItem("read-2"),
      thoughtItem("thought-1"),
      toolItem("read-3"),
      toolItem("read-4"),
    ]);

    expect(grouped.map((item) => item.type)).toEqual([
      "tool_group",
      "session_update",
      "tool_group",
    ]);
    expect(grouped[0]).toMatchObject({
      type: "tool_group",
      items: [{ id: "read-1" }, { id: "read-2" }],
    });
    expect(grouped[1]).toMatchObject({
      type: "session_update",
      id: "thought-1",
    });
    expect(grouped[2]).toMatchObject({
      type: "tool_group",
      items: [{ id: "read-3" }, { id: "read-4" }],
    });
  });
});
