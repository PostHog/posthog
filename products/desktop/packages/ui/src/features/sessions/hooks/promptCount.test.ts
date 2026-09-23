import type { AcpMessage } from "@posthog/shared";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { countUserPrompts } from "./promptCount";

const scanned = vi.hoisted(() => ({ count: 0 }));

vi.mock("@posthog/core/sessions/sessionEvents", async () => {
  const actual = await vi.importActual<
    typeof import("@posthog/core/sessions/sessionEvents")
  >("@posthog/core/sessions/sessionEvents");
  return {
    ...actual,
    extractUserPromptsFromEvents: (events: AcpMessage[]) => {
      scanned.count += events.length;
      return actual.extractUserPromptsFromEvents(events);
    },
  };
});

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
    scanned.count = 0;
  });

  it("counts appended prompts without rescanning and rescans a replaced transcript", () => {
    const first = [prompt("one"), chunk("a")];
    expect(countUserPrompts(first)).toBe(1);

    scanned.count = 0;
    const appended = [...first, chunk("b"), prompt("two")];
    expect(countUserPrompts(appended)).toBe(2);
    expect(scanned.count).toBe(2);

    const replaced = [prompt("x"), prompt("y"), prompt("z")];
    expect(countUserPrompts(replaced)).toBe(3);

    const shortened = replaced.slice(0, 1);
    expect(countUserPrompts(shortened)).toBe(1);
  });

  it("rebuilds when a middle segment is replaced between unchanged ends", () => {
    const head = prompt("one");
    const tail = chunk("tail");
    expect(countUserPrompts([head, prompt("two"), chunk("a"), tail])).toBe(2);

    const reconciled = [head, chunk("b"), chunk("c"), tail];
    expect(countUserPrompts(reconciled)).toBe(1);
  });

  it("scans a transcript once when it arrives after an empty one", () => {
    expect(countUserPrompts([])).toBe(0);

    const loaded = [prompt("one"), chunk("a")];
    expect(countUserPrompts(loaded)).toBe(1);
    expect(scanned.count).toBe(2);

    scanned.count = 0;
    expect(countUserPrompts([...loaded, prompt("two")])).toBe(2);
    expect(scanned.count).toBe(1);
  });

  it("keeps transcripts apart", () => {
    expect(countUserPrompts([prompt("one")])).toBe(1);
    expect(countUserPrompts(undefined)).toBe(0);
    expect(countUserPrompts([prompt("a"), prompt("b")])).toBe(2);
  });
});
