import * as fs from "node:fs/promises";
import * as path from "node:path";
import { GitSaga, type GitSagaInput } from "../git-saga";
import {
  addToLocalExclude,
  branchExists,
  fetchRef,
  getDefaultBranch,
  hasRef,
} from "../queries";
import { forceRemove, safeSymlink } from "../utils";
import { processWorktreeInclude, runPostCheckoutHook } from "../worktree";

export interface CreateWorktreeInput extends GitSagaInput {
  worktreePath: string;
  branchName: string;
  baseBranch?: string;
  /** Base the worktree on `origin/<baseBranch>` after fetching; falls back to the local ref if the fetch fails. */
  fetchBeforeCreate?: boolean;
}

export interface CreateWorktreeOutput {
  worktreePath: string;
  branchName: string;
  baseBranch: string;
}

export class CreateWorktreeSaga extends GitSaga<
  CreateWorktreeInput,
  CreateWorktreeOutput
> {
  readonly sagaName = "CreateWorktreeSaga";

  protected async executeGitOperations(
    input: CreateWorktreeInput,
  ): Promise<CreateWorktreeOutput> {
    const {
      baseDir,
      worktreePath,
      branchName,
      baseBranch,
      fetchBeforeCreate,
      signal,
    } = input;

    const base = await this.readOnlyStep("get-base-branch", async () => {
      if (baseBranch) return baseBranch;
      return getDefaultBranch(baseDir, { abortSignal: signal });
    });

    // Use `this.git` directly to avoid re-entering the write lock the saga already holds.
    const baseRef = fetchBeforeCreate
      ? await this.readOnlyStep("resolve-fresh-base-ref", async () => {
          const remote = "origin";
          const remoteRef = `${remote}/${base}`;
          const fetched = await fetchRef(this.git, remote, base);
          if (!fetched) return base;
          const exists = await hasRef(this.git, remoteRef);
          return exists ? remoteRef : base;
        })
      : base;

    await this.step({
      name: "create-worktree",
      execute: () =>
        this.git.raw([
          "-c",
          "core.hooksPath=/dev/null",
          "worktree",
          "add",
          "-b",
          branchName,
          worktreePath,
          baseRef,
        ]),
      rollback: async () => {
        try {
          await this.git.raw(["worktree", "remove", worktreePath, "--force"]);
        } catch {
          await forceRemove(worktreePath);
          await this.git.raw(["worktree", "prune"]);
        }
        try {
          await this.git.deleteLocalBranch(branchName, true);
        } catch {}
      },
    });

    await this.step({
      name: "symlink-claude-local-instructions",
      execute: async () => {
        const sourceClaudeLocalMd = path.join(baseDir, "CLAUDE.local.md");
        const targetClaudeLocalMd = path.join(worktreePath, "CLAUDE.local.md");
        const linkedFile = await safeSymlink(
          sourceClaudeLocalMd,
          targetClaudeLocalMd,
          "file",
        );
        if (linkedFile) {
          await addToLocalExclude(worktreePath, "CLAUDE.local.md", {
            abortSignal: signal,
          });
        }
      },
      rollback: async () => {
        const targetClaudeLocalMd = path.join(worktreePath, "CLAUDE.local.md");
        await fs.rm(targetClaudeLocalMd, { force: true }).catch(() => {});
      },
    });

    await this.step({
      name: "process-worktree-include",
      execute: () => processWorktreeInclude(baseDir, worktreePath),
      rollback: async () => {},
    });

    await this.step({
      name: "run-post-checkout-hook",
      execute: () => runPostCheckoutHook(baseDir, worktreePath),
      rollback: async () => {},
    });

    return { worktreePath, branchName, baseBranch: base };
  }
}

export interface CreateWorktreeForBranchInput extends GitSagaInput {
  worktreePath: string;
  branchName: string;
}

export interface CreateWorktreeForBranchOutput {
  worktreePath: string;
  branchName: string;
}

export class CreateWorktreeForBranchSaga extends GitSaga<
  CreateWorktreeForBranchInput,
  CreateWorktreeForBranchOutput
> {
  readonly sagaName = "CreateWorktreeForBranchSaga";

  protected async executeGitOperations(
    input: CreateWorktreeForBranchInput,
  ): Promise<CreateWorktreeForBranchOutput> {
    const { baseDir, worktreePath, branchName, signal } = input;

    await this.readOnlyStep("verify-branch-exists", async () => {
      const exists = await branchExists(baseDir, branchName, {
        abortSignal: signal,
      });
      if (!exists) {
        throw new Error(`Branch '${branchName}' does not exist`);
      }
    });

    await this.step({
      name: "create-worktree",
      execute: () =>
        this.git.raw([
          "-c",
          "core.hooksPath=/dev/null",
          "worktree",
          "add",
          worktreePath,
          branchName,
        ]),
      rollback: async () => {
        try {
          await this.git.raw(["worktree", "remove", worktreePath, "--force"]);
        } catch {
          await forceRemove(worktreePath);
          await this.git.raw(["worktree", "prune"]);
        }
      },
    });

    await this.step({
      name: "symlink-claude-local-instructions",
      execute: async () => {
        const sourceClaudeLocalMd = path.join(baseDir, "CLAUDE.local.md");
        const targetClaudeLocalMd = path.join(worktreePath, "CLAUDE.local.md");
        const linkedFile = await safeSymlink(
          sourceClaudeLocalMd,
          targetClaudeLocalMd,
          "file",
        );
        if (linkedFile) {
          await addToLocalExclude(worktreePath, "CLAUDE.local.md", {
            abortSignal: signal,
          });
        }
      },
      rollback: async () => {
        const targetClaudeLocalMd = path.join(worktreePath, "CLAUDE.local.md");
        await fs.rm(targetClaudeLocalMd, { force: true }).catch(() => {});
      },
    });

    await this.step({
      name: "process-worktree-include",
      execute: () => processWorktreeInclude(baseDir, worktreePath),
      rollback: async () => {},
    });

    await this.step({
      name: "run-post-checkout-hook",
      execute: () => runPostCheckoutHook(baseDir, worktreePath),
      rollback: async () => {},
    });

    return { worktreePath, branchName };
  }
}

export interface DeleteWorktreeInput extends GitSagaInput {
  worktreePath: string;
}

export interface DeleteWorktreeOutput {
  deleted: boolean;
}

export class DeleteWorktreeSaga extends GitSaga<
  DeleteWorktreeInput,
  DeleteWorktreeOutput
> {
  readonly sagaName = "DeleteWorktreeSaga";

  protected async executeGitOperations(
    input: DeleteWorktreeInput,
  ): Promise<DeleteWorktreeOutput> {
    const { baseDir, worktreePath } = input;

    const resolvedWorktreePath = path.resolve(worktreePath);
    const resolvedMainRepoPath = path.resolve(baseDir);

    await this.readOnlyStep("safety-checks", async () => {
      if (resolvedWorktreePath === resolvedMainRepoPath) {
        throw new Error("Cannot delete worktree: path matches main repo path");
      }
      if (
        resolvedMainRepoPath.startsWith(resolvedWorktreePath) &&
        resolvedMainRepoPath !== resolvedWorktreePath
      ) {
        throw new Error(
          "Cannot delete worktree: path is a parent of main repo path",
        );
      }
      try {
        const gitPath = path.join(resolvedWorktreePath, ".git");
        const stat = await fs.stat(gitPath);
        if (stat.isDirectory()) {
          throw new Error(
            "Cannot delete worktree: path appears to be a main repository",
          );
        }
      } catch (error) {
        if (
          error instanceof Error &&
          error.message.includes("Cannot delete worktree")
        ) {
          throw error;
        }
      }
    });

    await this.step({
      name: "delete-worktree",
      execute: async () => {
        try {
          await this.git.raw(["worktree", "remove", worktreePath, "--force"]);
        } catch {
          await forceRemove(worktreePath);
          await this.git.raw(["worktree", "prune"]);
        }
      },
      rollback: async () => {},
    });

    return { deleted: true };
  }
}
