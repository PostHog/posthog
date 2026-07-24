import { describe, expect, it } from "vitest";
import type { SessionEvent } from "../types";
import {
  countUserMessages,
  getSessionActivityPhase,
  isSessionAwaitingUserInput,
} from "./sessionActivity";

function buildUserMessage(text: string): SessionEvent {
  return {
    type: "session_update",
    ts: 1,
    notification: {
      update: {
        sessionUpdate: "user_message_chunk",
        content: { type: "text", text },
      },
    },
  } satisfies SessionEvent;
}

describe("countUserMessages", () => {
  it("counts only user_message_chunk events", () => {
    expect(
      countUserMessages([
        buildUserMessage("hello"),
        buildQuestionToolCall("pending"),
        buildUserMessage("again"),
      ]),
    ).toBe(2);
  });

  it("returns 0 for no events", () => {
    expect(countUserMessages()).toBe(0);
  });
});

function buildQuestionToolCall(
  status: "pending" | "in_progress" | "completed",
) {
  return {
    type: "session_update",
    ts: 1,
    notification: {
      update: {
        sessionUpdate: "tool_call",
        toolCallId: "question-1",
        status,
        rawInput: {
          questions: [{ question: "Proceed?", options: [] }],
        },
        _meta: {
          claudeCode: {
            toolName: "AskUserQuestion",
          },
        },
      },
    },
  } satisfies SessionEvent;
}

describe("getSessionActivityPhase", () => {
  it("treats retrying as connecting", () => {
    expect(
      getSessionActivityPhase({
        retrying: true,
        session: { isPromptPending: true, awaitingAgentOutput: false },
      }),
    ).toBe("connecting");
  });

  it("stays connecting until the agent emits visible output", () => {
    expect(
      getSessionActivityPhase({
        retrying: false,
        session: { isPromptPending: true, awaitingAgentOutput: true },
      }),
    ).toBe("connecting");
  });

  it("shows working only after the agent is actively in a turn", () => {
    expect(
      getSessionActivityPhase({
        retrying: false,
        session: { isPromptPending: true, awaitingAgentOutput: false },
      }),
    ).toBe("working");
  });

  it("returns idle once the agent is no longer working", () => {
    expect(
      getSessionActivityPhase({
        retrying: false,
        session: { isPromptPending: false, awaitingAgentOutput: false },
      }),
    ).toBe("idle");

    expect(
      getSessionActivityPhase({
        retrying: false,
        session: {
          isPromptPending: true,
          awaitingAgentOutput: false,
          terminalStatus: "completed",
        },
      }),
    ).toBe("idle");
  });

  it("returns idle while the agent is paused on a question tool", () => {
    expect(
      getSessionActivityPhase({
        retrying: false,
        session: {
          isPromptPending: true,
          awaitingAgentOutput: false,
          events: [buildQuestionToolCall("pending")],
        },
      }),
    ).toBe("idle");
  });
});

describe("isSessionAwaitingUserInput", () => {
  it("detects unresolved question tools", () => {
    expect(isSessionAwaitingUserInput([buildQuestionToolCall("pending")])).toBe(
      true,
    );
  });

  it("clears the waiting state once the user responds", () => {
    const events: SessionEvent[] = [
      buildQuestionToolCall("pending"),
      {
        type: "session_update",
        ts: 2,
        notification: {
          update: {
            sessionUpdate: "user_message_chunk",
            content: { type: "text", text: "Yes" },
          },
        },
      },
    ];

    expect(isSessionAwaitingUserInput(events)).toBe(false);
  });

  it("honors explicit awaiting-user-input backend markers", () => {
    const events: SessionEvent[] = [
      {
        type: "acp_message",
        direction: "agent",
        ts: 1,
        message: { method: "_posthog/awaiting_user_input" },
      },
    ];

    expect(isSessionAwaitingUserInput(events)).toBe(true);
  });
});
