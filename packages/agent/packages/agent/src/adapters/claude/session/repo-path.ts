import { listWorktrees } from "@posthog/git/queries";

/**
 * Resolves the primary worktree (main repository) path for a given cwd.
 *
 * Secondary git worktrees share a `.git` common directory with the primary
 * worktree. Returning the primary worktree path lets us scope per-repo
 * settings — such as "don't ask again" permission rules — to a single
 * location that every worktree of the same repository can read from.
 *
 * `git worktree list --porcelain` always emits the primary worktree first.
 * Returns `cwd` when the directory is not inside a git repository or when
 * git is unavailable.
 */
export async function resolveMainRepoPath(cwd: string): Promise<string> {
  try {
    const worktrees = await listWorktrees(cwd);
    return worktrees[0]?.path ?? cwd;
  } catch {
    return cwd;
  }
}
