import type { SupportTicket } from "@posthog/api-client/posthog-client";
import { describe, expect, it } from "vitest";
import { githubIssueUrl, slackThreadUrl } from "./ticketLinks";

describe("ticket channel links", () => {
  it.each<[string, Partial<SupportTicket>, string | null]>([
    [
      "a Slack thread",
      { slack_channel_id: "C0000000000", slack_thread_ts: "1712345678.901234" },
      "https://app.slack.com/archives/C0000000000/p1712345678901234",
    ],
    [
      "a channel with no thread",
      { slack_channel_id: "C0000000000", slack_thread_ts: null },
      null,
    ],
    ["a ticket from another channel", {}, null],
  ])("links %s", (_case, ticket, expected) => {
    expect(slackThreadUrl(ticket as SupportTicket)).toBe(expected);
  });

  it.each<[string, Partial<SupportTicket>, string | null]>([
    [
      "a linked issue",
      { github_repo: "ExampleOrg/example-repo", github_issue_number: 4321 },
      "https://github.com/ExampleOrg/example-repo/issues/4321",
    ],
    ["a repo with no issue", { github_repo: "ExampleOrg/example-repo" }, null],
    ["a ticket with no repo", {}, null],
  ])("links %s", (_case, ticket, expected) => {
    expect(githubIssueUrl(ticket as SupportTicket)).toBe(expected);
  });
});
