export type GithubRefKind = "issue" | "pr";

export interface ParsedGithubIssueUrl {
  kind: GithubRefKind;
  owner: string;
  repo: string;
  number: number;
  normalizedUrl: string;
}

const GITHUB_ISSUE_URL_PATTERN =
  /^https?:\/\/github\.com\/([^/\s]+)\/([^/\s]+)\/(issues|pull)\/(\d+)([/?#].*)?$/;

export function parseGithubIssueUrl(text: string): ParsedGithubIssueUrl | null {
  const trimmed = text.trim();
  const match = trimmed.match(GITHUB_ISSUE_URL_PATTERN);
  if (!match) return null;

  const [, owner, repo, segment, rawNumber, suffix = ""] = match;
  const number = Number(rawNumber);
  if (!Number.isInteger(number) || number <= 0) return null;

  const kind: GithubRefKind = segment === "pull" ? "pr" : "issue";
  // A fragment like #discussion_r123 anchors a specific comment, so keep the
  // whole suffix — anchors such as #r123 only resolve on the /files subpage
  // they were copied from. Without a fragment the tab/query suffix is noise.
  const hashIndex = suffix.indexOf("#");
  const hasFragment = hashIndex !== -1 && hashIndex < suffix.length - 1;
  return {
    kind,
    owner,
    repo,
    number,
    normalizedUrl: `https://github.com/${owner}/${repo}/${segment}/${number}${hasFragment ? suffix : ""}`,
  };
}
