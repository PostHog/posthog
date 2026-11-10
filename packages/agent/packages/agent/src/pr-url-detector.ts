const PR_URL_REGEX = /https:\/\/github\.com\/[^/\s"]+\/[^/\s"]+\/pull\/\d+/g;
// GitLab project paths can nest groups (`group/sub/project`), so the path has
// two or more segments before `/-/merge_requests/`.
const GITLAB_MR_URL_REGEX =
  /https:\/\/gitlab\.com\/(?:[A-Za-z0-9_.][A-Za-z0-9_.-]*\/){2,}-\/merge_requests\/\d+/g;

// A fixed window (not "since run start") so a PR the agent merely views on a
// long run is too old to be mistaken for one it just created.
export const PR_CREATION_RECENCY_MS = 5 * 60 * 1000;

export function findPrUrl(text: string): string | null {
  return findPrUrls(text)[0] ?? null;
}

export function findPrUrls(text: string): string[] {
  const matches = [
    ...text.matchAll(PR_URL_REGEX),
    ...text.matchAll(GITLAB_MR_URL_REGEX),
  ].sort((a, b) => (a.index ?? 0) - (b.index ?? 0));
  return [...new Set(matches.map((m) => m[0]))];
}

// Fails closed on missing/invalid input so we never attribute on uncertainty.
export function wasCreatedByLogin(
  author: string | null | undefined,
  login: string | null | undefined,
): boolean {
  if (!author || !login) return false;
  return author.toLowerCase() === login.toLowerCase();
}

// Fails closed on missing/invalid input so we never attribute on uncertainty.
export function wasCreatedRecently(
  createdAtIso: string | null | undefined,
  nowMs: number,
  maxAgeMs: number = PR_CREATION_RECENCY_MS,
): boolean {
  if (!createdAtIso) return false;
  const createdAt = new Date(createdAtIso);
  if (Number.isNaN(createdAt.getTime())) return false;
  return createdAt.getTime() >= nowMs - maxAgeMs;
}

// A branch this run pushed, as `owner/name` (lowercased) plus branch. `repository`
// is null when the run knows its branch but not which remote it points at.
export interface OwnedBranch {
  repository: string | null;
  branch: string;
}

export interface PrOwnershipEvidence {
  createdAt: string | null | undefined;
  nowMs: number;
  author: string | null | undefined;
  ghLogin: string | null | undefined;
  prRepository: string | null;
  headRefName: string | null | undefined;
  // True when the PR head lives in a fork. A fork's branch name is chosen by the
  // fork owner, so it can never prove this run opened the PR.
  isCrossRepository: boolean | null | undefined;
  ownedBranches: readonly OwnedBranch[];
  baseBranch?: string | null;
}

const PR_REPOSITORY_REGEX =
  /^https:\/\/github\.com\/([^/\s"]+\/[^/\s"]+)\/pull\/\d+/;
const GITLAB_MR_PROJECT_REGEX =
  /^https:\/\/gitlab\.com\/((?:[A-Za-z0-9_.][A-Za-z0-9_.-]*\/)+?[A-Za-z0-9_.][A-Za-z0-9_.-]*)\/-\/merge_requests\/\d+/;

export function isGitlabMergeRequestUrl(url: string): boolean {
  return GITLAB_MR_PROJECT_REGEX.test(url);
}

export function parsePrRepository(prUrl: string): string | null {
  const match =
    PR_REPOSITORY_REGEX.exec(prUrl) ?? GITLAB_MR_PROJECT_REGEX.exec(prUrl);
  return match ? match[1].toLowerCase() : null;
}

// Whether a PR URL seen in the agent's output is a PR this run opened, rather than
// one it read while checking GitHub for in-flight work. Recency is necessary but
// never sufficient on its own: a research run listing open PRs sees every PR the
// repo opened in the last few minutes. A fork PR never qualifies, because its head
// branch name is chosen by the fork owner, and neither does a head ref equal to
// the base branch, because a run sitting on the base cannot own a same-repo PR.
//
// With branch evidence on both sides (the PR's head, and branches this run pushed
// in that repository) the branch decides: a match is ownership, a mismatch is a PR
// the run only read, even when the author is this run's own login. On a desktop
// run the login is the person's, who authors most PRs in the repo, so a fresh PR
// of theirs from another branch would otherwise be re-attributed, which is the
// bug this gate exists to stop. The author match is the fallback only when branch
// evidence is missing on either side.
export function wasCreatedByThisRun(evidence: PrOwnershipEvidence): boolean {
  if (!wasCreatedRecently(evidence.createdAt, evidence.nowMs)) return false;
  if (evidence.isCrossRepository) return false;
  const { headRefName, baseBranch, prRepository } = evidence;
  if (headRefName && baseBranch && headRefName === baseBranch) return false;
  const comparable = evidence.ownedBranches.filter(
    (owned) =>
      !owned.repository || !prRepository || owned.repository === prRepository,
  );
  if (headRefName && comparable.length > 0) {
    return comparable.some((owned) => owned.branch === headRefName);
  }
  return wasCreatedByLogin(evidence.author, evidence.ghLogin);
}
