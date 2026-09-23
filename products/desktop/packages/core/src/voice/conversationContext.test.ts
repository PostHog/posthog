import { describe, expect, it } from "vitest";
import type { SessionActivityEvent } from "../sessions/sessionActivity";
import { voiceConversationContext } from "./conversationContext";

function message(kind: string, text: string, ts: number): SessionActivityEvent {
  return {
    type: "session_update",
    ts,
    notification: {
      update: { sessionUpdate: kind, content: { type: "text", text } },
    },
  };
}

describe("voiceConversationContext", () => {
  it("omits private reasoning and replaces chunks with the final answer", () => {
    const result = voiceConversationContext([
      message("user_message_chunk", "Check the task", 1),
      message("agent_thought_chunk", "Private reasoning", 2),
      message("agent_message_chunk", "The task ", 3),
      message("agent_message_chunk", "is ready.", 4),
      message("agent_message", "The task is ready.", 5),
    ]);
    expect(result.context).toBe(
      "User: Check the task\nAgent: The task is ready.",
    );
    expect(result.reply).toBe("The task is ready.");
    expect(result.replyKey).toBe("5:The task is ready.");
  });
});
