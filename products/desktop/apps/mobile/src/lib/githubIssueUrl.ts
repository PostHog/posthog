export type GithubRefKind = "issue" | "pr";

export interface ParsedGithubIssueUrl {
  kind: GithubRefKind;
  owner: string;
  repo: string;
  number: number;
  normalizedUrl: string;
}

const GITHUB_ISSUE_URL_PATTERN =
  /^https?:\/\/github\.com\/([^/\s]+)\/([^/\s]+)\/(issues|pull)\/(\d+)(?:[/?#].*)?$/;

export function parseGithubIssueUrl(text: string): ParsedGithubIssueUrl | null {
  const trimmed = text.trim();
  const match = trimmed.match(GITHUB_ISSUE_URL_PATTERN);
  if (!match) return null;

  const [, owner, repo, segment, rawNumber] = match;
  const number = Number(rawNumber);
  if (!Number.isInteger(number) || number <= 0) return null;

  const kind: GithubRefKind = segment === "pull" ? "pr" : "issue";
  return {
    kind,
    owner,
    repo,
    number,
    normalizedUrl: `https://github.com/${owner}/${repo}/${segment}/${number}`,
  };
}
