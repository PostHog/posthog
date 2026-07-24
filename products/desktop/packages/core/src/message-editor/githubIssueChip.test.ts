import { describe, expect, it } from "vitest";
import {
  GITHUB_ISSUE_STATE_COLORS,
  githubIssueStateColor,
  githubIssueToMentionChip,
} from "./githubIssueChip";

describe("githubIssueToMentionChip", () => {
  it("builds a chip with URL id and '#<number> - <title>' label", () => {
    expect(
      githubIssueToMentionChip({
        number: 1819,
        title: "Let me mention GH issues",
        url: "https://github.com/PostHog/code/issues/1819",
      }),
    ).toEqual({
      type: "github_issue",
      id: "https://github.com/PostHog/code/issues/1819",
      label: "#1819 - Let me mention GH issues",
    });
  });
});

describe("githubIssueStateColor", () => {
  it("returns the OPEN color", () => {
    expect(githubIssueStateColor("OPEN")).toBe(GITHUB_ISSUE_STATE_COLORS.OPEN);
  });

  it("returns the CLOSED color", () => {
    expect(githubIssueStateColor("CLOSED")).toBe(
      GITHUB_ISSUE_STATE_COLORS.CLOSED,
    );
  });

  it("returns the MERGED color", () => {
    expect(githubIssueStateColor("MERGED")).toBe(
      GITHUB_ISSUE_STATE_COLORS.MERGED,
    );
  });
});
