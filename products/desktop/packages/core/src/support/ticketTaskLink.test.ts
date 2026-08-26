import type {
  SupportTicket,
  SupportTicketMessage,
} from "@posthog/api-client/posthog-client";
import { describe, expect, it } from "vitest";
import {
  buildTicketAgentPrompt,
  isTicketTaskTag,
  readTicketTaskId,
  withTicketTaskId,
} from "./ticketTaskLink";

describe("ticket task link", () => {
  it.each<[string, string[] | undefined, string | null]>([
    ["no tags", undefined, null],
    ["unrelated tags", ["billing"], null],
    ["a linked task", ["ai-task:abc-123"], "abc-123"],
    ["a link among other tags", ["billing", "ai-task:xyz"], "xyz"],
    ["a differently cased prefix", ["AI-Task:abc"], "abc"],
    ["an empty link", ["ai-task:"], null],
    ["a link written before the rename", ["code-task:legacy-1"], "legacy-1"],
    [
      "both prefixes, preferring the current one",
      ["code-task:legacy-1", "ai-task:current-1"],
      "current-1",
    ],
  ])("reads the task id from %s", (_case, tags, expected) => {
    expect(readTicketTaskId(tags)).toBe(expected);
  });

  it.each<[string, string]>([
    ["the current prefix", "ai-task:abc"],
    ["the pre-rename prefix", "code-task:abc"],
    ["a conversation link", "max-conversation:abc"],
  ])("hides %s from the ticket's own tags", (_case, tag) => {
    expect(isTicketTaskTag(tag)).toBe(true);
  });

  it("keeps a tag someone typed", () => {
    expect(isTicketTaskTag("billing")).toBe(false);
  });

  it("replaces every machine link rather than adding a second", () => {
    expect(
      withTicketTaskId(
        [
          "ai-task:old",
          "code-task:older",
          "max-conversation:oldest",
          "billing",
        ],
        "new",
      ),
    ).toEqual(["billing", "ai-task:new"]);
  });

  it("briefs the agent with the ticket, the thread and the request", () => {
    const prompt = buildTicketAgentPrompt(
      { ticket_number: 4821, channel_source: "email" } as SupportTicket,
      [
        { author_name: "Priya", content: "Flags look stale" },
      ] as SupportTicketMessage[],
      "Find the cause",
    );

    expect(prompt).toContain("#4821");
    expect(prompt).toContain("Priya: Flags look stale");
    expect(prompt).toContain("Find the cause");
  });

  it("keeps only the tail of a long thread", () => {
    const messages = Array.from({ length: 30 }, (_, index) => ({
      author_name: "Priya",
      content: `Message ${index}`,
    })) as SupportTicketMessage[];

    const prompt = buildTicketAgentPrompt(
      { ticket_number: 1, channel_source: "email" } as SupportTicket,
      messages,
      "Summarize",
    );

    expect(prompt).not.toContain("Message 9:");
    expect(prompt).toContain("Message 29");
  });
});
