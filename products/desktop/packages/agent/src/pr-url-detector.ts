const PR_URL_REGEX = /https:\/\/github\.com\/[^/\s"]+\/[^/\s"]+\/pull\/\d+/g;

// A fixed window (not "since run start") so a PR the agent merely views on a
// long run is too old to be mistaken for one it just created.
export const PR_CREATION_RECENCY_MS = 5 * 60 * 1000;

export function findPrUrl(text: string): string | null {
  return findPrUrls(text)[0] ?? null;
}

export function findPrUrls(text: string): string[] {
  return [...new Set(text.match(PR_URL_REGEX) ?? [])];
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

export interface PrOwnershipEvidence {
  createdAt: string | null | undefined;
  nowMs: number;
  author: string | null | undefined;
  ghLogin: string | null | undefined;
  headRefName: string | null | undefined;
  currentBranch: string | null | undefined;
  baseBranch?: string | null;
}

// Whether a PR URL seen in the agent's output is a PR this run opened, rather than
// one it read while checking GitHub for in-flight work. Recency is necessary but
// never sufficient on its own: a research run listing open PRs sees every PR the
// repo opened in the last few minutes. Ownership needs one positive signal on top,
// either the PR's head branch is the branch this run has checked out, or the PR
// author is the identity this run pushes as. A run sitting on the base branch
// cannot own a same-repo PR, so a head ref equal to the base is rejected outright.
export function wasCreatedByThisRun(evidence: PrOwnershipEvidence): boolean {
  if (!wasCreatedRecently(evidence.createdAt, evidence.nowMs)) return false;
  const { headRefName, currentBranch, baseBranch } = evidence;
  if (headRefName && baseBranch && headRefName === baseBranch) return false;
  if (headRefName && currentBranch) {
    return headRefName === currentBranch;
  }
  return wasCreatedByLogin(evidence.author, evidence.ghLogin);
}
