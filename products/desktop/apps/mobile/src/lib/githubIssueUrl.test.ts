import { describe, expect, it } from "vitest";
import { parseGithubIssueUrl } from "./githubIssueUrl";

describe("parseGithubIssueUrl", () => {
  it.each([
    {
      name: "PR review comment via discussion anchor",
      url: "https://github.com/o/r/pull/12#discussion_r3647131256",
      isReviewComment: true,
    },
    {
      name: "PR review comment via files anchor",
      url: "https://github.com/o/r/pull/12/files#r3647131256",
      isReviewComment: true,
    },
    {
      name: "PR issue comment is not a review comment",
      url: "https://github.com/o/r/pull/12#issuecomment-123",
      isReviewComment: false,
    },
    {
      name: "issue with an r-style anchor is not a review comment",
      url: "https://github.com/o/r/issues/12#r3647131256",
      isReviewComment: false,
    },
    {
      name: "plain PR url",
      url: "https://github.com/o/r/pull/12",
      isReviewComment: false,
    },
    {
      name: "plain issue url",
      url: "https://github.com/o/r/issues/12",
      isReviewComment: false,
    },
  ])("$name", ({ url, isReviewComment }) => {
    expect(parseGithubIssueUrl(url)?.isReviewComment).toBe(isReviewComment);
  });

  it("keeps the comment anchor in the normalized url", () => {
    expect(
      parseGithubIssueUrl(
        "https://github.com/o/r/pull/12#discussion_r3647131256",
      )?.normalizedUrl,
    ).toBe("https://github.com/o/r/pull/12#discussion_r3647131256");
  });
});
