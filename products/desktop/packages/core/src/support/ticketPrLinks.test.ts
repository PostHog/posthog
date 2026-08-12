import { describe, expect, it } from "vitest";
import {
  readTicketPrUrls,
  resolveTicketPrUrls,
  ticketPrUrlFromTag,
} from "./ticketPrLinks";

describe("ticket pull request links", () => {
  it.each<[string, string, string | null]>([
    [
      "the slash form",
      "pr:PostHog/posthog/40000",
      "https://github.com/PostHog/posthog/pull/40000",
    ],
    [
      "the legacy hash form",
      "pr:PostHog/posthog#40000",
      "https://github.com/PostHog/posthog/pull/40000",
    ],
    [
      "a differently cased prefix",
      "PR:PostHog/posthog/1",
      "https://github.com/PostHog/posthog/pull/1",
    ],
    ["an unrelated tag", "billing", null],
    ["a prefix with nothing after it", "pr:", null],
    ["a missing number", "pr:PostHog/posthog", null],
    ["a non-numeric number", "pr:PostHog/posthog/abc", null],
    ["a missing repo", "pr:PostHog/40000", null],
  ])("reads %s", (_case, tag, expected) => {
    expect(ticketPrUrlFromTag(tag)).toBe(expected);
  });

  it("keeps tag order and drops duplicates", () => {
    expect(
      readTicketPrUrls([
        "billing",
        "pr:PostHog/posthog/2",
        "pr:PostHog/posthog/1",
        "pr:PostHog/posthog#2",
      ]),
    ).toEqual([
      "https://github.com/PostHog/posthog/pull/2",
      "https://github.com/PostHog/posthog/pull/1",
    ]);
  });

  it("lists attached pull requests before the thread's own", () => {
    expect(
      resolveTicketPrUrls(
        ["pr:PostHog/posthog/1"],
        ["https://github.com/PostHog/posthog/pull/9"],
      ),
    ).toEqual([
      "https://github.com/PostHog/posthog/pull/1",
      "https://github.com/PostHog/posthog/pull/9",
    ]);
  });

  it("counts a pull request the thread opened and someone attached only once", () => {
    expect(
      resolveTicketPrUrls(
        ["pr:PostHog/posthog/1"],
        ["https://github.com/PostHog/posthog/pull/1"],
      ),
    ).toEqual(["https://github.com/PostHog/posthog/pull/1"]);
  });

  it("has nothing to show for a ticket with no links", () => {
    expect(resolveTicketPrUrls(undefined, [])).toEqual([]);
  });
});
