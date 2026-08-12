import type {
  SupportTicket,
  SupportTicketMessage,
} from "@posthog/api-client/posthog-client";
import { describe, expect, it } from "vitest";
import {
  buildTicketAgentPrompt,
  readTicketTaskId,
  withTicketTaskId,
} from "./ticketTaskLink";

function message(
  overrides: Partial<SupportTicketMessage> = {},
): SupportTicketMessage {
  return {
    id: "00000000-0000-0000-0000-000000000000",
    content: "Body",
    rich_content: null,
    author_type: "customer",
    author_name: "Someone",
    is_private: false,
    version: 0,
    created_at: "2026-08-12T10:00:00Z",
    ...overrides,
  };
}

describe("ticket task link", () => {
  it.each<[string, string[] | undefined, string | null]>([
    ["no tags", undefined, null],
    ["unrelated tags", ["billing", "sdk"], null],
    ["a linked task", ["ai-task:abc-123"], "abc-123"],
    ["a link among other tags", ["billing", "ai-task:xyz"], "xyz"],
    ["a differently cased prefix", ["AI-Task:abc"], "abc"],
    ["an empty link", ["ai-task:"], null],
  ])("reads the task id from %s", (_case, tags, expected) => {
    expect(readTicketTaskId(tags)).toBe(expected);
  });

  it("keeps unrelated tags when linking", () => {
    expect(withTicketTaskId(["billing", "sdk"], "abc")).toEqual([
      "billing",
      "sdk",
      "ai-task:abc",
    ]);
  });

  it("replaces an existing link rather than adding a second", () => {
    expect(withTicketTaskId(["ai-task:old", "billing"], "new")).toEqual([
      "billing",
      "ai-task:new",
    ]);
  });

  describe("the agent prompt", () => {
    const ticket = {
      ticket_number: 4821,
      channel_source: "email",
      status: "open",
      priority: "high",
    } as SupportTicket;

    it("carries the ticket, the thread and the request", () => {
      const prompt = buildTicketAgentPrompt(
        ticket,
        [
          message({ content: "Flags look stale" }),
          message({
            content: "Reproduced it",
            author_type: "support",
            author_name: "Kim",
            is_private: true,
          }),
        ],
        "Find the cause",
      );

      expect(prompt).toContain("Ticket #4821");
      expect(prompt).toContain("Priority: high");
      expect(prompt).toContain("Flags look stale");
      expect(prompt).toContain("Kim (support) [internal note]: Reproduced it");
      expect(prompt).toContain("Find the cause");
    });

    it("keeps only the tail of a long thread", () => {
      const messages = Array.from({ length: 30 }, (_, index) =>
        message({ content: `Message ${index}` }),
      );

      const prompt = buildTicketAgentPrompt(ticket, messages, "Summarize");

      expect(prompt).not.toContain("Message 9:");
      expect(prompt).toContain("Message 29");
    });

    it("omits the transcript section for a ticket with no messages", () => {
      const prompt = buildTicketAgentPrompt(ticket, [], "What is this?");

      expect(prompt).not.toContain("Conversation so far");
      expect(prompt).toContain("What is this?");
    });
  });
});
