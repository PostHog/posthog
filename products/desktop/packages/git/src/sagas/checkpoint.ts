import { randomUUID } from "node:crypto";
import * as fs from "node:fs/promises";
import * as path from "node:path";
import { createGitClient, type GitClient } from "../client";
import { GitSaga, type GitSagaInput } from "../git-saga";
import { type GitBusyState, inspectGitBusyState } from "../queries";

export type { GitBusyState };

const CHECKPOINT_REF_PREFIX = "refs/posthog-code-checkpoint/";
const CHECKPOINT_VERSION = "v1";
const UNMERGED_INDEX_ERROR =
  "Cannot capture checkpoint with unresolved merge conflicts in the index";
const GIT_BUSY_ERROR =
  "Cannot capture checkpoint while git operation is in progress";
const CHECKPOINT_AUTHOR = {
  name: "PostHog Code",
  email: "posthog-code@local",
};

export interface CheckpointState {
  checkpointId: string;
  commit: string;
  head: string | null;
  branch: string | null;
  indexTree: string;
  worktreeTree: string;
  timestamp: string;
}

interface CheckpointMetadata {
  head: string | null;
  branch: string | null;
  indexTree: string | null;
  worktreeTree: string | null;
  timestamp: string | null;
}

export interface CaptureCheckpointInput extends GitSagaInput {
  checkpointId?: string;
}

export interface CaptureCheckpointOutput extends CheckpointState {}

export class CaptureCheckpointSaga extends GitSaga<
  CaptureCheckpointInput,
  CaptureCheckpointOutput
> {
  readonly sagaName = "CaptureCheckpointSaga";

  protected async executeGitOperations(
    input: CaptureCheckpointInput,
  ): Promise<CaptureCheckpointOutput> {
    const { baseDir } = input;

    const headInfo = await this.readOnlyStep("get_head_info", () =>
      getHeadInfo(this.git),
    );

    const busyState = await this.readOnlyStep("check_git_busy", () =>
      getGitBusyState(this.git),
    );
    if (busyState.busy) {
      throw new Error(`${GIT_BUSY_ERROR}: ${busyState.operation}`);
    }

    const hasUnmerged = await this.readOnlyStep("check_unmerged_index", () =>
      hasUnmergedEntries(this.git),
    );
    if (hasUnmerged) {
      throw new Error(UNMERGED_INDEX_ERROR);
    }

    const indexTree = await this.readOnlyStep("write_index_tree", () =>
      this.git.raw(["write-tree"]),
    );

    const worktreeTree = await this.readOnlyStep("write_worktree_tree", () =>
      createWorktreeTree(this.git, baseDir, headInfo.head),
    );

    const metaTree = await this.readOnlyStep("write_meta_tree", () =>
      createMetaTree(this.git, baseDir, indexTree.trim(), worktreeTree.trim()),
    );

    const timestamp = new Date().toISOString();
    const message = formatCheckpointMessage({
      head: headInfo.head,
      branch: headInfo.branch,
      indexTree: indexTree.trim(),
      worktreeTree: worktreeTree.trim(),
      timestamp,
    });

    const commitHash = await this.step({
      name: "create_checkpoint_commit",
      execute: async () => {
        const commitGit = this.git.env({
          ...process.env,
          GIT_AUTHOR_NAME: CHECKPOINT_AUTHOR.name,
          GIT_AUTHOR_EMAIL: CHECKPOINT_AUTHOR.email,
          GIT_COMMITTER_NAME: CHECKPOINT_AUTHOR.name,
          GIT_COMMITTER_EMAIL: CHECKPOINT_AUTHOR.email,
        });
        const rawCommit = await commitGit.raw([
          "commit-tree",
          metaTree.trim(),
          ...(headInfo.head ? ["-p", headInfo.head] : []),
          "-m",
          message,
        ]);
        return rawCommit.trim();
      },
      rollback: async () => {
        // Dangling commit objects are cleaned up by git gc
      },
    });

    const checkpointId = input.checkpointId ?? randomUUID();
    const refName = `${CHECKPOINT_REF_PREFIX}${checkpointId}`;

    const existingRef = await this.readOnlyStep(
      "check_existing_ref",
      async () => {
        try {
          await this.git.revparse(["--verify", refName]);
          return true;
        } catch {
          return false;
        }
      },
    );

    if (existingRef) {
      throw new Error(`Checkpoint ref already exists: ${refName}`);
    }

    await this.step({
      name: "update_checkpoint_ref",
      execute: () => this.git.raw(["update-ref", refName, commitHash]),
      rollback: async () => {
        await this.git.raw(["update-ref", "-d", refName]).catch(() => {});
      },
    });

    return {
      checkpointId,
      commit: commitHash,
      head: headInfo.head,
      branch: headInfo.branch,
      indexTree: indexTree.trim(),
      worktreeTree: worktreeTree.trim(),
      timestamp,
    };
  }
}

export interface RevertCheckpointInput extends GitSagaInput {
  checkpointId: string;
}

export interface RevertCheckpointOutput {
  checkpointId: string;
  commit: string;
  head: string | null;
  branch: string | null;
}

export class RevertCheckpointSaga extends GitSaga<
  RevertCheckpointInput,
  RevertCheckpointOutput
> {
  readonly sagaName = "RevertCheckpointSaga";

  protected async executeGitOperations(
    input: RevertCheckpointInput,
  ): Promise<RevertCheckpointOutput> {
    const { baseDir, checkpointId } = input;

    const checkpoint = await this.readOnlyStep("resolve_checkpoint", () =>
      resolveCheckpoint(this.git, checkpointId),
    );

    const { head, branch, indexTree, worktreeTree, commit } = checkpoint;

    if (!worktreeTree || !indexTree) {
      throw new Error("Checkpoint is missing tree data");
    }

    const originalState = await this.readOnlyStep(
      "capture_original_state",
      async () => {
        const origHead = await getHeadInfo(this.git);
        const origIndexTree = (await this.git.raw(["write-tree"])).trim();
        const origWorktreeTree = await createWorktreeTree(
          this.git,
          baseDir,
          origHead.head,
        );
        return {
          head: origHead.head,
          branch: origHead.branch,
          indexTree: origIndexTree,
          worktreeTree: origWorktreeTree,
        };
      },
    );

    await this.step({
      name: "checkout_head",
      execute: async () => {
        if (!head) return;
        if (branch) {
          const branchExists = await refExists(
            this.git,
            `refs/heads/${branch}`,
          );
          if (branchExists) {
            await this.git.checkout(branch);
          } else {
            await this.git.checkout(head);
          }
        } else {
          await this.git.checkout(head);
        }
      },
      rollback: async () => {
        if (originalState.branch) {
          const branchExists = await refExists(
            this.git,
            `refs/heads/${originalState.branch}`,
          );
          if (branchExists) {
            await this.git.checkout(originalState.branch);
            return;
          }
        }
        if (originalState.head) {
          await this.git.checkout(originalState.head);
        }
      },
    });

    if (head) {
      await this.step({
        name: "reset_head",
        execute: () => this.git.reset(["--hard", head]),
        rollback: async () => {
          if (originalState.head) {
            await this.git.reset(["--hard", originalState.head]);
          }
        },
      });
    }

    await this.step({
      name: "clean_worktree",
      execute: () => this.git.clean(["f", "d"]),
      rollback: async () => {
        await this.git.raw([
          "read-tree",
          "--reset",
          "-u",
          originalState.worktreeTree,
        ]);
      },
    });

    await this.step({
      name: "restore_worktree_tree",
      execute: () => this.git.raw(["read-tree", "--reset", "-u", worktreeTree]),
      rollback: async () => {
        await this.git.raw([
          "read-tree",
          "--reset",
          "-u",
          originalState.worktreeTree,
        ]);
      },
    });

    await this.step({
      name: "restore_index_tree",
      execute: () => this.git.raw(["read-tree", indexTree]),
      rollback: async () => {
        await this.git.raw(["read-tree", originalState.indexTree]);
      },
    });

    return {
      checkpointId,
      commit,
      head: head ?? null,
      branch: branch ?? null,
    };
  }
}

export interface DiffCheckpointInput extends GitSagaInput {
  from: string;
  to: string | "current";
}

export interface DiffCheckpointOutput {
  diff: string;
  fromTree: string;
  toTree: string;
}

export class DiffCheckpointSaga extends GitSaga<
  DiffCheckpointInput,
  DiffCheckpointOutput
> {
  readonly sagaName = "DiffCheckpointSaga";

  protected async executeGitOperations(
    input: DiffCheckpointInput,
  ): Promise<DiffCheckpointOutput> {
    const { baseDir, from, to } = input;

    const fromTree = await this.readOnlyStep("resolve_from_tree", async () => {
      const checkpoint = await resolveCheckpoint(this.git, from);
      if (!checkpoint.worktreeTree) {
        throw new Error("Checkpoint is missing worktree tree");
      }
      return checkpoint.worktreeTree;
    });

    const toTree = await this.readOnlyStep("resolve_to_tree", async () => {
      if (to === "current") {
        const head = await getHeadShaOrNull(this.git);
        return createWorktreeTree(this.git, baseDir, head);
      }

      const checkpoint = await resolveCheckpoint(this.git, to);
      if (!checkpoint.worktreeTree) {
        throw new Error("Checkpoint is missing worktree tree");
      }
      return checkpoint.worktreeTree;
    });

    const diff = await this.readOnlyStep("diff_trees", () =>
      this.git.raw(["--no-pager", "diff", "--no-color", fromTree, toTree]),
    );

    return {
      diff,
      fromTree,
      toTree,
    };
  }
}

async function getHeadInfo(git: GitClient): Promise<{
  head: string | null;
  branch: string | null;
}> {
  let head: string | null = null;
  let branch: string | null = null;

  try {
    head = (await git.revparse(["HEAD"]))?.trim() || null;
  } catch {
    head = null;
  }

  try {
    const rawBranch = await git.raw(["symbolic-ref", "--short", "HEAD"]);
    branch = rawBranch.trim() || null;
  } catch {
    branch = null;
  }

  return { head, branch };
}

async function getHeadShaOrNull(git: GitClient): Promise<string | null> {
  try {
    const head = await git.revparse(["HEAD"]);
    return head.trim() || null;
  } catch {
    return null;
  }
}

async function hasUnmergedEntries(git: GitClient): Promise<boolean> {
  const output = await git.raw(["ls-files", "--unmerged"]);
  return output.trim().length > 0;
}

export async function getGitBusyState(git: GitClient): Promise<GitBusyState> {
  return inspectGitBusyState(git);
}

const MAX_WORKTREE_FILE_BYTES = 1024 * 1024;

async function createWorktreeTree(
  git: GitClient,
  baseDir: string,
  head: string | null,
): Promise<string> {
  const { tempGit, tempIndexPath } = await createTempIndexGit(
    git,
    baseDir,
    "checkpoint-worktree",
  );

  try {
    if (head) {
      await tempGit.raw(["read-tree", head]);
    } else {
      await tempGit.raw(["read-tree", "--empty"]);
    }

    await tempGit.raw(["add", "-A", "--", "."]);
    await reconcileLargeBlobs(tempGit, head, MAX_WORKTREE_FILE_BYTES);
    const treeHash = await tempGit.raw(["write-tree"]);
    return treeHash.trim();
  } finally {
    await fs.rm(tempIndexPath, { force: true }).catch(() => {});
  }
}

async function reconcileLargeBlobs(
  tempGit: GitClient,
  head: string | null,
  maxBytes: number,
): Promise<void> {
  const intermediateTree = (await tempGit.raw(["write-tree"])).trim();
  const largePaths = await listLargeBlobPaths(
    tempGit,
    intermediateTree,
    maxBytes,
  );
  if (largePaths.length === 0) return;

  const headEntries = head
    ? await readHeadBlobEntries(tempGit, head, largePaths)
    : new Map<string, { mode: string; hash: string }>();

  for (const filePath of largePaths) {
    const headEntry = headEntries.get(filePath);
    if (headEntry) {
      await tempGit.raw([
        "update-index",
        "--cacheinfo",
        `${headEntry.mode},${headEntry.hash},${filePath}`,
      ]);
    } else {
      await tempGit
        .raw(["update-index", "--force-remove", filePath])
        .catch(() => {});
    }
  }
}

async function listLargeBlobPaths(
  tempGit: GitClient,
  tree: string,
  maxBytes: number,
): Promise<string[]> {
  const output = await tempGit.raw(["ls-tree", "-r", "-l", tree]);
  const result: string[] = [];
  for (const line of output.split("\n")) {
    if (!line) continue;
    const tabIndex = line.indexOf("\t");
    if (tabIndex < 0) continue;
    const meta = line.slice(0, tabIndex);
    const filePath = line.slice(tabIndex + 1);
    const parts = meta.split(/\s+/);
    if (parts.length < 4) continue;
    const [, type, , sizeStr] = parts;
    if (type !== "blob") continue;
    if (sizeStr === "-") continue;
    const size = Number.parseInt(sizeStr, 10);
    if (Number.isFinite(size) && size > maxBytes) {
      result.push(filePath);
    }
  }
  return result;
}

async function readHeadBlobEntries(
  tempGit: GitClient,
  head: string,
  paths: string[],
): Promise<Map<string, { mode: string; hash: string }>> {
  const result = new Map<string, { mode: string; hash: string }>();
  const CHUNK_SIZE = 100;
  for (let i = 0; i < paths.length; i += CHUNK_SIZE) {
    const chunk = paths.slice(i, i + CHUNK_SIZE);
    const output = await tempGit
      .raw(["ls-tree", "-r", head, "--", ...chunk])
      .catch(() => "");
    for (const line of output.split("\n")) {
      if (!line) continue;
      const tabIndex = line.indexOf("\t");
      if (tabIndex < 0) continue;
      const meta = line.slice(0, tabIndex);
      const filePath = line.slice(tabIndex + 1);
      const parts = meta.split(/\s+/);
      if (parts.length < 3) continue;
      const [mode, type, hash] = parts;
      if (type !== "blob") continue;
      result.set(filePath, { mode, hash });
    }
  }
  return result;
}

async function createMetaTree(
  git: GitClient,
  baseDir: string,
  indexTree: string,
  worktreeTree: string,
): Promise<string> {
  const { tempGit, tempIndexPath } = await createTempIndexGit(
    git,
    baseDir,
    "checkpoint-meta",
  );

  try {
    await tempGit.raw(["read-tree", "--empty"]);
    await tempGit.raw([
      "update-index",
      "--add",
      "--cacheinfo",
      "040000",
      indexTree,
      "index",
    ]);
    await tempGit.raw([
      "update-index",
      "--add",
      "--cacheinfo",
      "040000",
      worktreeTree,
      "worktree",
    ]);
    const metaTree = await tempGit.raw(["write-tree"]);
    return metaTree.trim();
  } finally {
    await fs.rm(tempIndexPath, { force: true }).catch(() => {});
  }
}

function formatCheckpointMessage(meta: {
  head: string | null;
  branch: string | null;
  indexTree: string;
  worktreeTree: string;
  timestamp: string;
}): string {
  return [
    `POSTHOG-CODE-CHECKPOINT ${CHECKPOINT_VERSION}`,
    `head=${meta.head ?? "null"}`,
    `branch=${meta.branch ?? "null"}`,
    `index=${meta.indexTree}`,
    `worktree=${meta.worktreeTree}`,
    `timestamp=${meta.timestamp}`,
  ].join("\n");
}

async function getGitCommonDir(
  git: GitClient,
  baseDir: string,
): Promise<string> {
  const raw = await git.raw(["rev-parse", "--git-common-dir"]);
  const dir = raw.trim() || ".git";
  return path.isAbsolute(dir) ? dir : path.resolve(baseDir, dir);
}

async function createTempIndexGit(
  git: GitClient,
  baseDir: string,
  label: string,
): Promise<{ tempGit: GitClient; tempIndexPath: string }> {
  const tmpDir = path.join(
    await getGitCommonDir(git, baseDir),
    "posthog-code-tmp",
  );
  await fs.mkdir(tmpDir, { recursive: true });

  const tempIndexPath = path.join(
    tmpDir,
    `${label}-${Date.now()}-${randomUUID()}`,
  );
  const tempGit = createGitClient(baseDir).env({
    ...process.env,
    GIT_INDEX_FILE: tempIndexPath,
  });

  return { tempGit, tempIndexPath };
}

function parseCheckpointMessage(message: string): CheckpointMetadata {
  const meta: CheckpointMetadata = {
    head: null,
    branch: null,
    indexTree: null,
    worktreeTree: null,
    timestamp: null,
  };

  const lines = message
    .split("\n")
    .map((line) => line.trim())
    .filter(Boolean);

  if (!lines[0]?.startsWith("POSTHOG-CODE-CHECKPOINT")) {
    throw new Error("Not a posthog-code checkpoint commit");
  }

  for (const line of lines.slice(1)) {
    const [key, ...rest] = line.split("=");
    if (!key || rest.length === 0) continue;
    const value = rest.join("=").trim();

    switch (key) {
      case "head":
        meta.head = value === "null" ? null : value;
        break;
      case "branch":
        meta.branch = value === "null" ? null : value;
        break;
      case "index":
        meta.indexTree = value || null;
        break;
      case "worktree":
        meta.worktreeTree = value || null;
        break;
      case "timestamp":
        meta.timestamp = value || null;
        break;
      default:
        break;
    }
  }

  return meta;
}

async function resolveCheckpoint(
  git: GitClient,
  checkpointId: string,
): Promise<{
  commit: string;
  head: string | null;
  branch: string | null;
  indexTree: string | null;
  worktreeTree: string | null;
  timestamp: string | null;
}> {
  const refName = `${CHECKPOINT_REF_PREFIX}${checkpointId}`;
  const commit = await resolveCheckpointCommit(git, checkpointId, refName);

  const message = await git.raw(["show", "-s", "--format=%B", commit]);
  const meta = parseCheckpointMessage(message);

  const treeHash = await getCommitTree(git, commit);
  const treeEntries = treeHash ? await readMetaTree(git, treeHash) : null;

  const indexTree = meta.indexTree ?? treeEntries?.indexTree ?? null;
  const worktreeTree = meta.worktreeTree ?? treeEntries?.worktreeTree ?? null;

  return {
    commit,
    head: meta.head,
    branch: meta.branch,
    indexTree,
    worktreeTree,
    timestamp: meta.timestamp,
  };
}

async function resolveCheckpointCommit(
  git: GitClient,
  checkpointId: string,
  refName: string,
): Promise<string> {
  try {
    const commit = await git.revparse([refName]);
    return commit.trim();
  } catch {
    try {
      const commit = await git.revparse([checkpointId]);
      return commit.trim();
    } catch {
      throw new Error(`Checkpoint not found: ${checkpointId}`);
    }
  }
}

async function getCommitTree(
  git: GitClient,
  commit: string,
): Promise<string | null> {
  const raw = await git.raw(["cat-file", "-p", commit]);
  const line = raw.split("\n").find((l) => l.startsWith("tree "));
  return line ? line.split(" ")[1]?.trim() || null : null;
}

async function readMetaTree(
  git: GitClient,
  treeHash: string,
): Promise<{ indexTree: string | null; worktreeTree: string | null }> {
  const raw = await git.raw(["ls-tree", treeHash]);
  let indexTree: string | null = null;
  let worktreeTree: string | null = null;

  for (const line of raw.split("\n")) {
    if (!line.trim()) continue;
    const [meta, name] = line.split("\t");
    const parts = meta.split(" ");
    const hash = parts[2];
    if (name === "index") indexTree = hash;
    if (name === "worktree") worktreeTree = hash;
  }

  return { indexTree, worktreeTree };
}

async function refExists(git: GitClient, refName: string): Promise<boolean> {
  try {
    await git.revparse(["--verify", refName]);
    return true;
  } catch {
    return false;
  }
}

export interface CheckpointInfo {
  checkpointId: string;
  commit: string;
  head: string | null;
  branch: string | null;
  timestamp: string | null;
}

export async function listCheckpoints(
  git: GitClient,
): Promise<CheckpointInfo[]> {
  const output = await git.raw([
    "for-each-ref",
    "--format=%(refname)",
    CHECKPOINT_REF_PREFIX,
  ]);
  const refs = output.trim().split("\n").filter(Boolean);

  const checkpoints: CheckpointInfo[] = [];
  for (const ref of refs) {
    const checkpointId = ref.replace(CHECKPOINT_REF_PREFIX, "");
    try {
      const resolved = await resolveCheckpoint(git, checkpointId);
      checkpoints.push({
        checkpointId,
        commit: resolved.commit,
        head: resolved.head,
        branch: resolved.branch,
        timestamp: resolved.timestamp,
      });
    } catch {}
  }

  return checkpoints.sort((a, b) => {
    if (!a.timestamp || !b.timestamp) return 0;
    return b.timestamp.localeCompare(a.timestamp);
  });
}

export async function deleteCheckpoint(
  git: GitClient,
  checkpointId: string,
): Promise<void> {
  const refName = `${CHECKPOINT_REF_PREFIX}${checkpointId}`;
  const exists = await refExists(git, refName);
  if (!exists) {
    throw new Error(`Checkpoint not found: ${checkpointId}`);
  }
  await git.raw(["update-ref", "-d", refName]);
}
