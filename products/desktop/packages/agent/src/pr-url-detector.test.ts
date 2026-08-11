import { describe, expect, it } from "vitest";
import {
  findPrUrl,
  findPrUrls,
  wasCreatedByLogin,
  wasCreatedRecently,
} from "./pr-url-detector";

const PR_URL = "https://github.com/PostHog/posthog.com/pull/17764";

describe("findPrUrl", () => {
  it("finds a PR URL in serialized terminal output (the cloud-sandbox framing)", () => {
    const update = JSON.stringify({
      sessionUpdate: "tool_call_update",
      _meta: { terminal_output: `Creating draft pull request...\n${PR_URL}\n` },
    });
    expect(findPrUrl(update)).toBe(PR_URL);
  });

  it("finds a PR URL in an agent message", () => {
    expect(findPrUrl(`Draft PR opened: ${PR_URL} — please review`)).toBe(
      PR_URL,
    );
  });

  it("finds a PR URL when the repo name contains a dot", () => {
    expect(findPrUrl(`{"text":"opened ${PR_URL}"}`)).toBe(PR_URL);
  });

  it("returns null when there is no PR URL", () => {
    expect(findPrUrl('{"sessionUpdate":"agent_thought_chunk"}')).toBeNull();
  });

  it("ignores non-pull github URLs (issues, etc.)", () => {
    expect(
      findPrUrl("see https://github.com/PostHog/posthog/issues/42"),
    ).toBeNull();
  });
});

describe("findPrUrls", () => {
  const OTHER = "https://github.com/PostHog/posthog/pull/99";

  it("finds every PR URL in one chunk, in order", () => {
    expect(findPrUrls(`Opened ${PR_URL} and ${OTHER} today`)).toEqual([
      PR_URL,
      OTHER,
    ]);
  });

  it("dedupes repeated mentions of the same PR", () => {
    expect(findPrUrls(`${PR_URL} again: ${PR_URL}`)).toEqual([PR_URL]);
  });

  it("returns an empty array when there is no PR URL", () => {
    expect(findPrUrls("nothing here")).toEqual([]);
  });
});

describe("wasCreatedByLogin", () => {
  it.each([
    ["run-owner", "run-owner", true],
    ["Run-Owner", "run-owner", true],
    ["someone-else", "run-owner", false],
    [null, "run-owner", false],
    ["run-owner", null, false],
    ["", "", false],
  ] as const)("author=%s login=%s -> %s", (author, login, expected) => {
    expect(wasCreatedByLogin(author, login)).toBe(expected);
  });
});

describe("wasCreatedRecently", () => {
  const now = new Date("2026-06-18T17:00:00Z").getTime();
  const maxAge = 15 * 60 * 1000;

  it("attributes a PR created moments ago (just created by this run)", () => {
    expect(wasCreatedRecently("2026-06-18T16:58:00Z", now, maxAge)).toBe(true);
  });

  it("does NOT attribute an older PR even within a long run (viewed, not created)", () => {
    // Created 3h ago — would pass a 'since run start' check on a long run, but
    // the recency cap correctly excludes it.
    expect(wasCreatedRecently("2026-06-18T14:00:00Z", now, maxAge)).toBe(false);
  });

  it("tolerates small clock skew (createdAt slightly in the future)", () => {
    expect(wasCreatedRecently("2026-06-18T17:00:30Z", now, maxAge)).toBe(true);
  });

  it("fails closed on missing createdAt", () => {
    expect(wasCreatedRecently(null, now, maxAge)).toBe(false);
    expect(wasCreatedRecently(undefined, now, maxAge)).toBe(false);
  });

  it("fails closed on an unparseable createdAt", () => {
    expect(wasCreatedRecently("not-a-date", now, maxAge)).toBe(false);
  });
});
