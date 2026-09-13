import type { AcpMessage } from "@posthog/shared";
import { beforeEach, describe, expect, it } from "vitest";
import { countUserPrompts, resetPromptCountsForTests } from "./promptCount";

function prompt(text: string): AcpMessage {
  return {
    type: "acp_message",
    ts: 1,
    message: {
      jsonrpc: "2.0",
      id: text,
      method: "session/prompt",
      params: { prompt: [{ type: "text", text }] },
    },
  } as unknown as AcpMessage;
}

function chunk(text: string): AcpMessage {
  return {
    type: "acp_message",
    ts: 1,
    message: {
      jsonrpc: "2.0",
      method: "session/update",
      params: {
        update: {
          sessionUpdate: "agent_message_chunk",
          content: { type: "text", text },
        },
      },
    },
  } as unknown as AcpMessage;
}

describe("countUserPrompts", () => {
  beforeEach(() => {
    resetPromptCountsForTests();
  });

  it("counts appended prompts without rescanning and rescans a replaced transcript", () => {
    const first = [prompt("one"), chunk("a")];
    expect(countUserPrompts("run", first)).toBe(1);

    const appended = [...first, chunk("b"), prompt("two")];
    expect(countUserPrompts("run", appended)).toBe(2);

    const replaced = [prompt("x"), prompt("y"), prompt("z")];
    expect(countUserPrompts("run", replaced)).toBe(3);

    const shortened = replaced.slice(0, 1);
    expect(countUserPrompts("run", shortened)).toBe(1);
  });

  it("keeps runs apart", () => {
    expect(countUserPrompts("a", [prompt("one")])).toBe(1);
    expect(countUserPrompts("b", [])).toBe(0);
    expect(countUserPrompts("a", [prompt("one"), prompt("two")])).toBe(2);
  });
});
