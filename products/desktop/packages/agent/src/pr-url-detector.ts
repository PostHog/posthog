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
