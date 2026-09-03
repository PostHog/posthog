import type {
  AvailableSuggestedReviewer,
  SuggestedReviewer,
} from "@posthog/shared/types";
import { describe, expect, it } from "vitest";
import {
  buildReviewerOptions,
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
      expected: [{ github_login: "ada" }],
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
});
