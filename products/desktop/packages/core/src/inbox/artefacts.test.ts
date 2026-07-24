import type { SuggestedReviewer } from "@posthog/shared/types";
import { describe, expect, it } from "vitest";
import {
  extractSuggestedReviewers,
  reviewerInitials,
  suggestedReviewerDisplayName,
} from "./artefacts";

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

  it("derives reviewer initials from names and emails", () => {
    expect(reviewerInitials("Ben W.", null)).toBe("BW");
    expect(reviewerInitials("", "ben@posthog.com")).toBe("BE");
  });
});
