import { describe, expect, it } from "vitest";
import type {
  PortableSessionEvent,
  PortableSessionToolCallStatus,
} from "./portableSessionEvents";
import {
  countUserMessages,
  getSessionActivityPhase,
  isSessionAwaitingUserInput,
} from "./sessionActivity";

function userMessage(ts = 1): PortableSessionEvent {
  return {
    type: "session_update",
    ts,
    notification: {
      update: {
        sessionUpdate: "user_message_chunk",
        content: { type: "text", text: "Yes" },
      },
    },
  };
}

function questionToolCall(
  status: PortableSessionToolCallStatus,
  sessionUpdate = "tool_call",
): PortableSessionEvent {
  return {
    type: "session_update",
    ts: 1,
    notification: {
      update: {
        sessionUpdate,
        toolCallId: "question-1",
        status,
        rawInput: { questions: [{ question: "Proceed?", options: [] }] },
        _meta: { claudeCode: { toolName: "AskUserQuestion" } },
      },
    },
  };
}

function acpNotification(method: string): PortableSessionEvent {
  return {
    type: "acp_message",
    direction: "agent",
    ts: 1,
    message: { method },
  };
}

describe("isSessionAwaitingUserInput", () => {
  it("tracks question tools until a metadata-free completion update", () => {
    const completion: PortableSessionEvent = {
      type: "session_update",
      ts: 2,
      notification: {
        update: {
          sessionUpdate: "tool_call_update",
          toolCallId: "question-1",
          status: "completed",
        },
      },
    };

    expect(
      isSessionAwaitingUserInput([questionToolCall("pending"), completion]),
    ).toBe(false);
  });

  it("clears questions when the user responds", () => {
    expect(
      isSessionAwaitingUserInput([questionToolCall("pending"), userMessage(2)]),
    ).toBe(false);
  });

  it("honors explicit waiting and terminal backend markers", () => {
    expect(
      isSessionAwaitingUserInput([
        acpNotification("_posthog/awaiting_user_input"),
      ]),
    ).toBe(true);
    expect(
      isSessionAwaitingUserInput([
        acpNotification("_posthog/awaiting_user_input"),
        acpNotification("_posthog/turn_complete"),
      ]),
    ).toBe(false);
  });
});

describe("countUserMessages", () => {
  it("counts only projected user message updates", () => {
    expect(
      countUserMessages([
        userMessage(),
        questionToolCall("pending"),
        userMessage(2),
      ]),
    ).toBe(2);
  });
});

describe("getSessionActivityPhase", () => {
  it.each([
    ["retrying", true, undefined, "connecting"],
    [
      "awaiting agent output",
      false,
      { isPromptPending: true, awaitingAgentOutput: true },
      "connecting",
    ],
    [
      "working",
      false,
      { isPromptPending: true, awaitingAgentOutput: false },
      "working",
    ],
    [
      "not pending",
      false,
      { isPromptPending: false, awaitingAgentOutput: false },
      "idle",
    ],
    [
      "terminal",
      false,
      {
        isPromptPending: true,
        awaitingAgentOutput: false,
        terminalStatus: "completed" as const,
      },
      "idle",
    ],
    [
      "waiting for user",
      false,
      {
        isPromptPending: true,
        awaitingAgentOutput: false,
        events: [questionToolCall("pending")],
      },
      "idle",
    ],
  ] as const)(
    "returns the expected phase while %s",
    (_name, retrying, session, expected) => {
      expect(getSessionActivityPhase({ retrying, session })).toBe(expected);
    },
  );
});
