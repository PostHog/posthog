export const BRANCH_PREFIX = "posthog/";

export const WORKTREE_NAMING_SCHEMES = ["codename", "descriptive"] as const;

export type WorktreeNamingScheme = (typeof WORKTREE_NAMING_SCHEMES)[number];

export const DEFAULT_WORKTREE_NAMING_SCHEME: WorktreeNamingScheme = "codename";

const MAX_SLUG_LENGTH = 60;

/**
 * Reduces free-form text (a task title, a branch name) to a short
 * filesystem-safe slug: lowercase a-z, digits, and hyphens, capped at
 * 60 chars. Returns null when nothing usable remains.
 */
export function slugifyWorktreeName(input: string): string | null {
  const slug = input
    .toLowerCase()
    .trim()
    .replace(/[^a-z0-9-]+/g, "-")
    .replace(/-{2,}/g, "-")
    .replace(/^-|-$/g, "")
    .slice(0, MAX_SLUG_LENGTH)
    .replace(/-$/, "");
  return slug || null;
}

/**
 * Derives a worktree folder slug from a branch name, dropping the app's
 * branch prefix so `posthog-code/fix-login` becomes `fix-login`.
 */
export function worktreeNameFromBranch(branch: string): string | null {
  const withoutPrefix = branch.startsWith(BRANCH_PREFIX)
    ? branch.slice(BRANCH_PREFIX.length)
    : branch;
  return slugifyWorktreeName(withoutPrefix);
}
