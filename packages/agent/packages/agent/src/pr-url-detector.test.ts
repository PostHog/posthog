import { describe, expect, it } from "vitest";
import {
  findPrUrl,
  findPrUrls,
  parsePrRepository,
  wasCreatedByLogin,
  wasCreatedByThisRun,
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

describe("parsePrRepository", () => {
  it.each([
    ["https://github.com/PostHog/posthog/pull/123", "posthog/posthog"],
    ["https://github.com/PostHog/posthog.com/pull/1", "posthog/posthog.com"],
    ["https://example.com/PostHog/posthog/pull/1", null],
  ])("%s -> %s", (url, expected) => {
    expect(parsePrRepository(url)).toBe(expected);
  });
});

describe("wasCreatedByThisRun", () => {
  const nowMs = new Date("2026-06-18T17:00:00Z").getTime();
  const fresh = "2026-06-18T16:59:00Z";
  const stale = "2026-06-18T12:00:00Z";
  const ours = { repository: "posthog/posthog", branch: "run/branch" };
  const base = {
    createdAt: fresh,
    nowMs,
    author: "app/posthog",
    ghLogin: null,
    prRepository: "posthog/posthog",
    headRefName: "run/branch",
    isCrossRepository: false,
    ownedBranches: [ours],
    baseBranch: "master",
  };

  it.each([
    ["fresh PR on a branch the run pushed", {}, true],
    [
      "fresh PR on another branch, run on master",
      {
        headRefName: "their/branch",
        ownedBranches: [{ repository: "posthog/posthog", branch: "master" }],
      },
      false,
    ],
    [
      "fresh PR whose head is the base branch",
      {
        headRefName: "master",
        ownedBranches: [{ repository: "posthog/posthog", branch: "master" }],
      },
      false,
    ],
    ["fork PR with a matching branch name", { isCrossRepository: true }, false],
    [
      "same branch name in a different repository",
      { prRepository: "posthog/posthog.com" },
      false,
    ],
    [
      "same branch name, run repository unknown",
      { ownedBranches: [{ repository: null, branch: "run/branch" }] },
      true,
    ],
    [
      "branch pushed by signed commit, no checkout",
      {
        ownedBranches: [
          { repository: "posthog/posthog", branch: "run/branch" },
        ],
      },
      true,
    ],
    ["stale PR on the run's branch", { createdAt: stale }, false],
    [
      "fresh PR, no branches known, author matches login",
      { headRefName: null, ownedBranches: [], ghLogin: "me", author: "me" },
      true,
    ],
    [
      "fresh PR, no branches known, author unknown",
      { headRefName: null, ownedBranches: [] },
      false,
    ],
    [
      "fresh PR from another branch, author matches login",
      { headRefName: "other/branch", ghLogin: "me", author: "me" },
      false,
    ],
    [
      "fresh PR, head known but no branches pushed, author matches login",
      { ownedBranches: [], ghLogin: "me", author: "me" },
      true,
    ],
    [
      "fresh PR, only branches in other repositories known, author matches login",
      {
        ownedBranches: [
          { repository: "posthog/posthog.com", branch: "run/branch" },
        ],
        ghLogin: "me",
        author: "me",
      },
      true,
    ],
    [
      "fresh fork PR, author matches login",
      { isCrossRepository: true, ghLogin: "me", author: "me" },
      false,
    ],
  ] as const)("%s -> %s", (_name, overrides, expected) => {
    expect(wasCreatedByThisRun({ ...base, ...overrides })).toBe(expected);
  });
});
