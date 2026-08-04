import { describe, expect, it } from "vitest";
import type { SessionNotification } from "@agentclientprotocol/sdk";
import {
  getLatestAssistantText,
  getLatestAssistantTextExtended,
  isPlanReady,
} from "./utils";

function textNotification(text: string): SessionNotification {
  return {
    sessionId: "s",
    update: {
      sessionUpdate: "agent_message_chunk",
      content: { type: "text", text },
    },
  } as unknown as SessionNotification;
}

function toolCallNotification(toolName: string): SessionNotification {
  return {
    sessionId: "s",
    update: {
      sessionUpdate: "tool_call",
      _meta: { claudeCode: { toolName } },
    },
  } as unknown as SessionNotification;
}

describe("isPlanReady", () => {
  it("accepts a markdown-headed plan", () => {
    expect(isPlanReady("# Plan\n\n1. do a thing\n2. do another thing\n3. profit")).toBe(
      true,
    );
  });

  it("rejects short plans", () => {
    expect(isPlanReady("tiny")).toBe(false);
    expect(isPlanReady("short heading-only-ish text")).toBe(false);
  });

  it("rejects heading-less single-line text", () => {
    expect(
      isPlanReady(
        "a single long line of prose that goes on and on without any headings or breaks",
      ),
    ).toBe(false);
  });

  it("accepts multi-line plain-text plans (no heading)", () => {
    const plan = [
      "Here is what I will do:",
      "First step is to read the file and understand the layout.",
      "Second step is to write the migration in the right directory.",
      "Finally I will run the test suite to make sure nothing regressed.",
    ].join("\n");
    expect(isPlanReady(plan)).toBe(true);
  });
});

describe("getLatestAssistantText", () => {
  it("returns the latest contiguous assistant text", () => {
    const notifications = [
      textNotification("first"),
      textNotification(" second"),
      toolCallNotification("Read"),
      textNotification("third"),
    ];
    expect(getLatestAssistantText(notifications)).toBe("third");
  });

  it("returns null when the last notification is not text", () => {
    const notifications = [
      textNotification("here is the plan"),
      toolCallNotification("ExitPlanMode"),
    ];
    expect(getLatestAssistantText(notifications)).toBeNull();
  });

  it("returns null on empty history", () => {
    expect(getLatestAssistantText([])).toBeNull();
  });
});

describe("getLatestAssistantTextExtended", () => {
  it("skips a trailing ExitPlanMode call to find earlier text", () => {
    const notifications = [
      textNotification("# Plan\n\nstep one\nstep two\nstep three"),
      toolCallNotification("ExitPlanMode"),
    ];
    expect(getLatestAssistantTextExtended(notifications)).toBe(
      "# Plan\n\nstep one\nstep two\nstep three",
    );
  });

  it("scans past other tool calls when collecting fallback text", () => {
    const notifications = [
      textNotification("some text"),
      toolCallNotification("Bash"),
    ];
    expect(getLatestAssistantTextExtended(notifications)).toBe("some text");
  });

  it("returns null when there is no earlier text to recover", () => {
    const notifications = [toolCallNotification("ExitPlanMode")];
    expect(getLatestAssistantTextExtended(notifications)).toBeNull();
  });

  it("still returns trailing text when present", () => {
    const notifications = [
      textNotification("earlier"),
      toolCallNotification("ExitPlanMode"),
      textNotification("final draft"),
    ];
    expect(getLatestAssistantTextExtended(notifications)).toBe("final draft");
  });
});
