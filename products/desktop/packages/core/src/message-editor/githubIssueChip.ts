import type { GithubRefState } from "@posthog/shared";
import type { MentionChip } from "./content";
import type { ParsedGithubIssueUrl } from "./githubIssueUrl";

export interface GithubIssueChipSource {
  number: number;
  title: string;
  url: string;
}

export function githubIssueToMentionChip(
  issue: GithubIssueChipSource,
): MentionChip {
  return {
    type: "github_issue",
    id: issue.url,
    label: `#${issue.number} - ${issue.title}`,
  };
}

export function githubPullRequestToMentionChip(
  pr: GithubIssueChipSource,
): MentionChip {
  return {
    type: "github_pr",
    id: pr.url,
    label: `#${pr.number} - ${pr.title}`,
  };
}

export const GITHUB_ISSUE_STATE_COLORS: Record<GithubRefState, string> = {
  OPEN: "#238636",
  CLOSED: "#AB7DF8",
  MERGED: "#8957E5",
};

export function githubIssueStateColor(state: GithubRefState): string {
  return GITHUB_ISSUE_STATE_COLORS[state];
}

export function buildGithubRefPlaceholderChip(
  parsed: ParsedGithubIssueUrl,
): MentionChip {
  const source = {
    number: parsed.number,
    title: "Loading...",
    url: parsed.normalizedUrl,
  };
  return parsed.kind === "pr"
    ? githubPullRequestToMentionChip(source)
    : githubIssueToMentionChip(source);
}
