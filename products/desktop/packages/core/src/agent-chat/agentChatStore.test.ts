import type { AcpMessage } from "@posthog/shared";
import { beforeEach, describe, expect, it } from "vitest";
import { agentChatStore, MAX_CHAT_MESSAGES } from "./agentChatStore";

const message = (i: number): AcpMessage =>
  ({
    message: {
      jsonrpc: "2.0",
      method: "session/update",
      params: { i },
    },
  }) as unknown as AcpMessage;

describe("agentChatStore", () => {
  beforeEach(() => {
    agentChatStore.setState({ chats: {} });
  });

  it("appends messages in order", () => {
    const { begin, appendMessages } = agentChatStore.getState();
    begin("chat", "agent");
    appendMessages("chat", [message(1), message(2)]);
    appendMessages("chat", [message(3)]);

    expect(agentChatStore.getState().chats.chat?.messages).toHaveLength(3);
  });

  it("caps retained messages at MAX_CHAT_MESSAGES, dropping oldest", () => {
    const { begin, appendMessages } = agentChatStore.getState();
    begin("chat", "agent");

    const batch = Array.from({ length: MAX_CHAT_MESSAGES }, (_, i) =>
      message(i),
    );
    appendMessages("chat", batch);
    appendMessages("chat", [message(MAX_CHAT_MESSAGES)]);

    const messages = agentChatStore.getState().chats.chat?.messages ?? [];
    expect(messages).toHaveLength(MAX_CHAT_MESSAGES);
    const first = messages[0]?.message as { params?: { i?: number } };
    const last = messages.at(-1)?.message as { params?: { i?: number } };
    expect(first.params?.i).toBe(1);
    expect(last.params?.i).toBe(MAX_CHAT_MESSAGES);
  });
});
