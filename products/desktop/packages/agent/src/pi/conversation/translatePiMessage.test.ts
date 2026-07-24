import type { AssistantMessage, UserMessage } from "@earendil-works/pi-ai";
import { describe, expect, it } from "vitest";
import { createPiMessageTranslator } from "./translatePiMessage";

function makeAssistant(content: AssistantMessage["content"]): AssistantMessage {
  return {
    role: "assistant",
    content,
    api: "anthropic-messages" as AssistantMessage["api"],
    provider: "anthropic" as AssistantMessage["provider"],
    model: "test-model",
    usage: {
      input: 0,
      output: 0,
      cacheRead: 0,
      cacheWrite: 0,
      totalTokens: 0,
      cost: { input: 0, output: 0, cacheRead: 0, cacheWrite: 0, total: 0 },
    },
    stopReason: "stop",
    timestamp: 0,
  };
}

describe("createPiMessageTranslator", () => {
  it("translates a string user message into a user message chunk", () => {
    const translator = createPiMessageTranslator();

    const message: UserMessage = {
      role: "user",
      content: "hello there",
      timestamp: 0,
    };

    expect(translator.translate(message)).toEqual([
      {
        type: "user_message",
        id: "pi-user-0-1",
        timestamp: 0,
        content: [{ type: "text", text: "hello there" }],
      },
    ]);
  });

  it("translates user message content blocks into user message chunks", () => {
    const translator = createPiMessageTranslator();

    const message: UserMessage = {
      role: "user",
      content: [
        { type: "text", text: "first" },
        { type: "image", data: "abc", mimeType: "image/png" },
      ],
      timestamp: 0,
    };

    expect(translator.translate(message)).toEqual([
      {
        type: "user_message",
        id: "pi-user-0-1",
        timestamp: 0,
        content: [
          { type: "text", text: "first" },
          { type: "image", data: "abc", mimeType: "image/png" },
        ],
      },
    ]);
  });

  it("translates a plain text assistant message into an agent message chunk", () => {
    const translator = createPiMessageTranslator();

    const message = makeAssistant([{ type: "text", text: "working on it" }]);

    expect(translator.translate(message)).toEqual([
      {
        type: "assistant_message_chunk",
        timestamp: 0,
        content: { type: "text", text: "working on it" },
      },
    ]);
  });

  it("translates assistant runtime errors", () => {
    const translator = createPiMessageTranslator();
    const message = makeAssistant([]);
    message.stopReason = "error";
    message.errorMessage = "Provider unavailable";

    expect(translator.translate(message)).toEqual([
      {
        type: "runtime_error",
        timestamp: 0,
        errorType: "pi_runtime",
        message: "Provider unavailable",
      },
    ]);
  });

  it("translates assistant thinking into an agent thought chunk", () => {
    const translator = createPiMessageTranslator();

    const message = makeAssistant([{ type: "thinking", thinking: "hmm" }]);

    expect(translator.translate(message)).toEqual([
      {
        type: "assistant_thought_chunk",
        timestamp: 0,
        content: { type: "text", text: "hmm" },
      },
    ]);
  });
});
