import type {
  AvailableSuggestedReviewer,
  SuggestedReviewer,
} from "@posthog/shared/types";
import { describe, expect, it } from "vitest";
import {
  buildReviewerOptions,
  buildSuggestedReviewerItems,
  extractActionabilityExplanation,
  extractSuggestedReviewers,
  orderSuggestedReviewers,
  reviewerMatchesAvailable,
  reviewerOptionLabel,
  suggestedReviewerDisplayName,
  toSuggestedReviewerWriteContent,
} from "./artefacts";

function makeReviewer(
  partial: Partial<SuggestedReviewer> = {},
): SuggestedReviewer {
  return {
    github_login: "octocat",
    github_name: "The Octocat",
    relevant_commits: [],
    user: null,
    ...partial,
  };
}

function makeAvailableReviewer(
  partial: Partial<AvailableSuggestedReviewer> = {},
): AvailableSuggestedReviewer {
  return {
    uuid: "uuid-1",
    name: "Ada Lovelace",
    email: "ada@example.com",
    github_login: "ada",
    ...partial,
  };
}

describe("artefacts", () => {
  it("extracts suggested reviewers from artefacts", () => {
    const reviewers: SuggestedReviewer[] = [
      {
        github_login: "benw",
        github_name: "Ben W.",
        relevant_commits: [],
        user: null,
      },
    ];

    expect(
      extractSuggestedReviewers([
        { type: "priority_judgment", content: {} },
        { type: "suggested_reviewers", content: reviewers },
      ]),
    ).toEqual(reviewers);
  });

  it("prefers user names for display", () => {
    expect(
      suggestedReviewerDisplayName({
        github_login: "benw",
        github_name: "Ben W.",
        relevant_commits: [],
        user: {
          id: 1,
          uuid: "uuid-1",
          email: "ben@posthog.com",
          first_name: "Ben",
          last_name: "W.",
        },
      }),
    ).toBe("Ben W.");
  });

  it("groups repeated reviewer reasons within the same source category", () => {
    const sharedReason = "Maintains the request execution parser.";
    const reviewer = (
      id: string,
      sourceLabel: string,
      sourceSkill: string | null,
      explanation: string | null = sharedReason,
    ): SuggestedReviewer =>
      makeReviewer({
        github_login: id,
        github_name: id,
        relevant_commits:
          sourceLabel === "Code history"
            ? [
                {
                  sha: "abc123f",
                  url: "https://example.com/c/abc123f",
                  reason: explanation ?? "",
                },
              ]
            : [],
        source_skill: sourceSkill,
        source_label: sourceLabel,
        explanation,
      });

    const items = buildSuggestedReviewerItems([
      reviewer("avery", "Runtime ownership scout", "runtime-ownership"),
      reviewer("jordan", "Code history", null),
      reviewer("morgan", "Infrastructure scout", "infrastructure"),
      reviewer("taylor", "Code history", null),
      reviewer(
        "rowan",
        "Runtime ownership scout",
        "runtime-ownership",
        `${sharedReason} `,
      ),
      reviewer("casey", "Agent suggestion", null, null),
    ]);

    expect(items.map((item) => [item.kind, item.key])).toEqual([
      [
        "reason-group",
        JSON.stringify(["reason-group", sharedReason, "scout", null]),
      ],
      [
        "reason-group",
        JSON.stringify(["reason-group", sharedReason, "other", "Code history"]),
      ],
      ["person", "rowan"],
      ["person", "casey"],
    ]);
    expect(items[0]?.kind === "reason-group" && items[0].reviewers).toEqual([
      expect.objectContaining({ github_login: "avery" }),
      expect.objectContaining({ github_login: "morgan" }),
    ]);
  });

  it("moves the current user to the front", () => {
    const reviewers = [
      makeReviewer({
        github_login: "a",
        user: {
          id: 1,
          uuid: "uuid-a",
          email: "a@posthog.com",
          first_name: "a",
          last_name: "",
        },
      }),
      makeReviewer({
        github_login: "me",
        user: {
          id: 2,
          uuid: "uuid-me",
          email: "me@posthog.com",
          first_name: "me",
          last_name: "",
        },
      }),
    ];

    expect(
      orderSuggestedReviewers(reviewers, "uuid-me").map(
        (reviewer) => reviewer.github_login,
      ),
    ).toEqual(["me", "a"]);
  });

  it("deduplicates reviewer options and pins the current user first", () => {
    const options = buildReviewerOptions(
      [
        makeAvailableReviewer({ uuid: "b", name: "Bob" }),
        makeAvailableReviewer({ uuid: "a", name: "Ada" }),
        makeAvailableReviewer({ uuid: "a", name: "Ada duplicate" }),
      ],
      "b",
    );

    expect(options.map((option) => option.uuid)).toEqual(["b", "a"]);
  });

  it("labels the current reviewer", () => {
    expect(
      reviewerOptionLabel({
        uuid: "uuid-me",
        name: "Ada",
        email: "ada@example.com",
        github_login: "ada",
        isMe: true,
      }),
    ).toBe("Ada (Me)");
  });

  it.each([
    {
      name: "user uuid",
      reviewer: makeReviewer({
        github_login: "",
        user: {
          id: 1,
          uuid: "uuid-1",
          email: "",
          first_name: "",
          last_name: "",
        },
      }),
      expected: true,
    },
    {
      name: "case-insensitive GitHub login",
      reviewer: makeReviewer({ github_login: "ADA" }),
      expected: true,
    },
    {
      name: "different reviewer",
      reviewer: makeReviewer(),
      expected: false,
    },
  ])("matches an available reviewer by $name", ({ reviewer, expected }) => {
    expect(reviewerMatchesAvailable(reviewer, makeAvailableReviewer())).toBe(
      expected,
    );
  });

  it.each([
    {
      name: "GitHub login",
      reviewer: makeReviewer({
        github_login: "ada",
        user: {
          id: 1,
          uuid: "uuid-1",
          email: "",
          first_name: "",
          last_name: "",
        },
      }),
      expected: [{ user_uuid: "uuid-1" }],
    },
    {
      name: "stored user uuid",
      reviewer: makeReviewer({
        github_login: "stale-login",
        user_uuid: "uuid-stable",
        user: null,
      }),
      expected: [{ user_uuid: "uuid-stable" }],
    },
    {
      name: "user uuid fallback",
      reviewer: makeReviewer({
        github_login: "",
        user: {
          id: 1,
          uuid: "uuid-1",
          email: "",
          first_name: "",
          last_name: "",
        },
      }),
      expected: [{ user_uuid: "uuid-1" }],
    },
    {
      name: "unresolved reviewer",
      reviewer: makeReviewer({ github_login: "" }),
      expected: [],
    },
  ])("builds write content from the $name", ({ reviewer, expected }) => {
    expect(toSuggestedReviewerWriteContent([reviewer])).toEqual(expected);
  });

  describe("extractActionabilityExplanation", () => {
    const judgment = (created_at: string, explanation: unknown) => ({
      type: "actionability_judgment",
      created_at,
      content: { actionability: "not_actionable", explanation },
    });

    it("takes the reasoning from the newest judgment, whatever the list order", () => {
      expect(
        extractActionabilityExplanation([
          judgment("2026-01-02T00:00:00Z", "The behavior is expected."),
          { type: "note", created_at: "2026-01-03T00:00:00Z", content: {} },
          judgment("2026-01-01T00:00:00Z", "Too vague to act on."),
        ]),
      ).toBe("The behavior is expected.");
    });

    it.each([
      ["no artefacts", undefined],
      [
        "no judgment",
        [{ type: "note", created_at: "2026-01-01T00:00:00Z", content: {} }],
      ],
      ["a blank explanation", [judgment("2026-01-01T00:00:00Z", "   ")]],
      ["a non-string explanation", [judgment("2026-01-01T00:00:00Z", 7)]],
    ])("returns null for %s", (_label, results) => {
      expect(extractActionabilityExplanation(results)).toBeNull();
    });
  });
});
