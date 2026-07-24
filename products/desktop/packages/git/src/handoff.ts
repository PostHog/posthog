import { spawn } from "node:child_process";
import { copyFile, mkdtemp, readFile, rm, stat } from "node:fs/promises";
import path from "node:path";
import type {
  GitHandoffCheckpoint,
  HandoffLocalGitState,
  SagaLogger,
} from "@posthog/shared";
import { createGitClient, type GitClient } from "./client";
import { CaptureCheckpointSaga, deleteCheckpoint } from "./sagas/checkpoint";

export type {
  GitHandoffCheckpoint,
  HandoffLocalGitState,
} from "@posthog/shared";

const HANDOFF_HEAD_REF_PREFIX = "refs/posthog-code-handoff/head/";
const CHECKPOINT_REF_PREFIX = "refs/posthog-code-checkpoint/";
const MAX_HANDOFF_FILE_BYTES = 1024 * 1024;

export interface GitHandoffArtifactFile {
  path: string;
  rawBytes: number;
}

export interface GitHandoffCaptureResult {
  checkpoint: GitHandoffCheckpoint;
  artifactDirectory: string;
  headPack?: GitHandoffArtifactFile;
  indexFile: GitHandoffArtifactFile;
  totalBytes: number;
}

export interface GitHandoffApplyInput {
  checkpoint: GitHandoffCheckpoint;
  headPackPath?: string;
  indexPath?: string;
  localGitState?: HandoffLocalGitState;
  onDivergedBranch?: (
    divergence: GitHandoffBranchDivergence,
  ) => Promise<boolean>;
}

export interface GitHandoffApplyResult {
  packBytes: number;
  indexBytes: number;
  totalBytes: number;
}

export interface GitHandoffBranchDivergence {
  branch: string;
  localHead: string;
  cloudHead: string;
}

export interface GitHandoffTrackerConfig {
  repositoryPath: string;
  logger?: SagaLogger;
}

interface GitTrackingMetadata {
  upstreamRemote: string | null;
  upstreamMergeRef: string | null;
  remoteUrl: string | null;
}

type GitBranchRestoreStatus =
  | { kind: "missing" }
  | { kind: "match" }
  | { kind: "fast_forward" }
  | { kind: "diverged"; divergence: GitHandoffBranchDivergence };

export class GitHandoffTracker {
  private repositoryPath: string;
  private logger?: SagaLogger;

  constructor(config: GitHandoffTrackerConfig) {
    this.repositoryPath = config.repositoryPath;
    this.logger = config.logger;
  }

  async captureForHandoff(
    localGitState?: HandoffLocalGitState,
  ): Promise<GitHandoffCaptureResult> {
    const captureSaga = new CaptureCheckpointSaga(this.logger);
    const result = await captureSaga.run({ baseDir: this.repositoryPath });
    if (!result.success) {
      throw new Error(
        `Failed to capture checkpoint at step '${result.failedStep}': ${result.error}`,
      );
    }

    const checkpoint = result.data;
    const git = createGitClient(this.repositoryPath);
    const tempDir = await this.createTempDir(git, checkpoint.checkpointId);
    const checkpointRef = `${CHECKPOINT_REF_PREFIX}${checkpoint.checkpointId}`;

    try {
      const reconciledIndex = await this.reconcileHandoffIndex(
        git,
        checkpoint.head,
        checkpoint.indexTree,
        tempDir,
        checkpoint.checkpointId,
      );

      const tracking = await getTrackingMetadata(git, checkpoint.branch);
      const baselineRefs = localGitState?.upstreamHead
        ? [localGitState.upstreamHead]
        : await this.resolveDefaultPackBaseline(git, tracking);
      const packRefs = [
        checkpoint.head,
        reconciledIndex.indexTree,
        checkpoint.worktreeTree,
        ...baselineRefs.map((ref) => `^${ref}`),
      ].filter((ref): ref is string => !!ref);
      const headRef = checkpoint.head
        ? `${HANDOFF_HEAD_REF_PREFIX}${checkpoint.checkpointId}`
        : undefined;
      const packPrefix = path.join(tempDir, checkpoint.checkpointId);

      const [headPack, indexFile] = await Promise.all([
        this.captureObjectPack(packPrefix, packRefs),
        this.statFileArtifact(reconciledIndex.indexFilePath),
      ]);

      return {
        checkpoint: {
          checkpointId: checkpoint.checkpointId,
          commit: checkpoint.commit,
          checkpointRef,
          headRef,
          head: checkpoint.head,
          branch: checkpoint.branch,
          indexTree: reconciledIndex.indexTree,
          worktreeTree: checkpoint.worktreeTree,
          timestamp: checkpoint.timestamp,
          upstreamRemote: tracking.upstreamRemote,
          upstreamMergeRef: tracking.upstreamMergeRef,
          remoteUrl: tracking.remoteUrl,
        },
        artifactDirectory: tempDir,
        headPack,
        indexFile,
        totalBytes: (headPack?.rawBytes ?? 0) + indexFile.rawBytes,
      };
    } catch (error) {
      await rm(tempDir, { recursive: true, force: true }).catch(() => {});
      throw error;
    } finally {
      await deleteCheckpoint(git, checkpoint.checkpointId).catch(() => {});
    }
  }

  async applyFromHandoff(
    input: GitHandoffApplyInput,
  ): Promise<GitHandoffApplyResult> {
    const {
      checkpoint,
      headPackPath,
      indexPath,
      localGitState,
      onDivergedBranch,
    } = input;
    const git = createGitClient(this.repositoryPath);

    if (headPackPath) {
      await this.ensureBaselineForApply(git, checkpoint, localGitState);
      await this.unpackPackFile(headPackPath);
    }

    if (checkpoint.branch && checkpoint.head) {
      const branchStatus = await this.resolveBranchRestoreStatus(
        git,
        checkpoint.branch,
        checkpoint.head,
        localGitState,
      );
      const tracking = this.getPreferredTracking(localGitState, checkpoint);

      if (
        branchStatus.kind === "diverged" &&
        !(await onDivergedBranch?.(branchStatus.divergence))
      ) {
        throw new Error(
          `Handoff aborted: local branch '${checkpoint.branch}' has diverged`,
        );
      }

      await this.checkoutBranchAtHead(git, checkpoint.branch, checkpoint.head);

      if (this.shouldRestoreTracking(branchStatus, localGitState, tracking)) {
        await this.ensureRemoteForTracking(git, tracking);
        await this.configureUpstream(git, checkpoint.branch, tracking);
      }
    } else if (checkpoint.head) {
      await git.checkout(checkpoint.head);
    }

    await git.clean(["f", "d"]);
    await git.raw(["read-tree", "--reset", "-u", checkpoint.worktreeTree]);

    if (indexPath) {
      await this.restoreIndexFile(git, indexPath);
    }

    const packBytes = headPackPath ? await this.getFileSize(headPackPath) : 0;
    const indexBytes = indexPath ? await this.getFileSize(indexPath) : 0;

    return {
      packBytes,
      indexBytes,
      totalBytes: packBytes + indexBytes,
    };
  }

  /**
   * Without local handoff state the pack baseline must stay limited to
   * objects the apply side is able to restore: the branch's upstream
   * tracking ref (which ensureBaselineForApply fetches before unpacking),
   * or failing that the remote's default branch, which any fresh clone of
   * the repository already contains. Excluding broader refs (e.g. every
   * remote-tracking ref) risks producing a pack that omits objects the
   * resume repository cannot fetch. Without any baseline, a capture with no
   * local handoff state packs the entire repo snapshot, which for large
   * repos exceeds artifact upload limits.
   */
  private async resolveDefaultPackBaseline(
    git: GitClient,
    tracking: GitTrackingMetadata,
  ): Promise<string[]> {
    if (tracking.upstreamRemote && tracking.upstreamMergeRef) {
      const branchName = tracking.upstreamMergeRef.replace(
        /^refs\/heads\//,
        "",
      );
      const upstreamHead = await this.revparseOrNull(
        git,
        `refs/remotes/${tracking.upstreamRemote}/${branchName}`,
      );
      if (upstreamHead) {
        return [upstreamHead];
      }
    }

    const defaultHead = await this.revparseOrNull(
      git,
      "refs/remotes/origin/HEAD",
    );
    return defaultHead ? [defaultHead] : [];
  }

  private async revparseOrNull(
    git: GitClient,
    ref: string,
  ): Promise<string | null> {
    const value = await git.revparse([ref]).catch(() => null);
    return value ? value.trim() : null;
  }

  private async captureObjectPack(
    packPrefix: string,
    refs: string[],
  ): Promise<GitHandoffArtifactFile> {
    const hash = await this.runGitWithInput(
      ["pack-objects", packPrefix, "--revs"],
      `${refs.join("\n")}\n`,
    );
    const packPath = `${packPrefix}-${hash.trim()}.pack`;
    const rawBytes = await this.getFileSize(packPath);
    await rm(`${packPath}.idx`, { force: true }).catch(() => {});
    return { path: packPath, rawBytes };
  }

  private async reconcileHandoffIndex(
    git: GitClient,
    head: string | null,
    indexTree: string,
    tempDir: string,
    checkpointId: string,
  ): Promise<{ indexTree: string; indexFilePath: string }> {
    const realIndexPath = await this.getGitPath(git, "index");
    const tempIndexPath = path.join(tempDir, `${checkpointId}.index`);
    await copyFile(realIndexPath, tempIndexPath);

    const largePaths = await this.listLargeBlobsInTree(
      indexTree,
      MAX_HANDOFF_FILE_BYTES,
    );
    if (largePaths.length === 0) {
      return { indexTree, indexFilePath: tempIndexPath };
    }

    const headBlobs = head
      ? await this.readHeadBlobsForPaths(head, largePaths)
      : new Map<string, { mode: string; hash: string }>();

    const env = { ...process.env, GIT_INDEX_FILE: tempIndexPath };
    for (const filePath of largePaths) {
      const headBlob = headBlobs.get(filePath);
      if (headBlob) {
        await this.runGitWithEnv(env, [
          "update-index",
          "--cacheinfo",
          `${headBlob.mode},${headBlob.hash},${filePath}`,
        ]);
      } else {
        await this.runGitWithEnv(env, [
          "update-index",
          "--force-remove",
          filePath,
        ]).catch(() => {});
      }
    }

    const reconciledTree = (
      await this.runGitWithEnv(env, ["write-tree"])
    ).trim();
    return { indexTree: reconciledTree, indexFilePath: tempIndexPath };
  }

  private async listLargeBlobsInTree(
    tree: string,
    maxBytes: number,
  ): Promise<string[]> {
    const { stdout } = await this.runGitProcess(
      ["ls-tree", "-r", "-l", tree],
      "",
    );
    const result: string[] = [];
    for (const line of stdout.split("\n")) {
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

  private async readHeadBlobsForPaths(
    head: string,
    paths: string[],
  ): Promise<Map<string, { mode: string; hash: string }>> {
    const result = new Map<string, { mode: string; hash: string }>();
    const CHUNK_SIZE = 100;
    for (let i = 0; i < paths.length; i += CHUNK_SIZE) {
      const chunk = paths.slice(i, i + CHUNK_SIZE);
      const { stdout } = await this.runGitProcess(
        ["ls-tree", "-r", head, "--", ...chunk],
        "",
      ).catch(() => ({ stdout: "", stderr: "" }));
      for (const line of stdout.split("\n")) {
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

  private async statFileArtifact(
    filePath: string,
  ): Promise<GitHandoffArtifactFile> {
    return { path: filePath, rawBytes: await this.getFileSize(filePath) };
  }

  private async restoreIndexFile(
    git: GitClient,
    indexPath: string,
  ): Promise<void> {
    const gitIndexPath = await this.getGitPath(git, "index");
    await copyFile(indexPath, gitIndexPath);
  }

  private async unpackPackFile(packPath: string): Promise<void> {
    const content = await readFile(packPath);
    await this.runGitWithBuffer(["unpack-objects", "-r"], content);
  }

  private getPreferredTracking(
    localGitState: HandoffLocalGitState | undefined,
    checkpoint: GitHandoffCheckpoint,
  ): GitTrackingMetadata {
    const state = localGitState;
    if (state && hasTrackingConfig(state)) {
      return {
        upstreamRemote: state.upstreamRemote ?? null,
        upstreamMergeRef: state.upstreamMergeRef ?? null,
        remoteUrl:
          state.upstreamRemote &&
          state.upstreamRemote === checkpoint.upstreamRemote
            ? checkpoint.remoteUrl
            : null,
      };
    }

    return {
      upstreamRemote: checkpoint.upstreamRemote,
      upstreamMergeRef: checkpoint.upstreamMergeRef,
      remoteUrl: checkpoint.remoteUrl,
    };
  }

  private shouldRestoreTracking(
    branchStatus: GitBranchRestoreStatus,
    localGitState: HandoffLocalGitState | undefined,
    tracking: GitTrackingMetadata,
  ): boolean {
    return (
      branchStatus.kind === "missing" ||
      (!hasTrackingConfig(localGitState) &&
        (tracking.upstreamRemote !== null ||
          tracking.upstreamMergeRef !== null))
    );
  }

  private async ensureBaselineForApply(
    git: GitClient,
    checkpoint: GitHandoffCheckpoint,
    localGitState: HandoffLocalGitState | undefined,
  ): Promise<void> {
    const tracking = this.getPreferredTracking(localGitState, checkpoint);
    if (!tracking.upstreamRemote || !tracking.upstreamMergeRef) return;

    await this.ensureRemoteForTracking(git, tracking).catch(() => {});
    await git
      .raw(["fetch", tracking.upstreamRemote, tracking.upstreamMergeRef])
      .catch((err) => {
        this.logger?.error(
          "Handoff baseline fetch failed; if the pack excludes commits the receiver does not already have, the subsequent unpack/read-tree will fail with an object-missing error",
          {
            err: String(err),
            remote: tracking.upstreamRemote,
            ref: tracking.upstreamMergeRef,
          },
        );
      });
  }

  private async ensureRemoteForTracking(
    git: GitClient,
    tracking: GitTrackingMetadata,
  ): Promise<void> {
    if (!tracking.upstreamRemote || !tracking.remoteUrl) return;

    const remotes = await git.getRemotes(true);
    const existing = remotes.find(
      (remote) => remote.name === tracking.upstreamRemote,
    );

    if (!existing) {
      await git.addRemote(tracking.upstreamRemote, tracking.remoteUrl);
    }
  }

  private async configureUpstream(
    git: GitClient,
    branch: string,
    tracking: GitTrackingMetadata,
  ): Promise<void> {
    if (tracking.upstreamRemote) {
      await git.raw([
        "config",
        `branch.${branch}.remote`,
        tracking.upstreamRemote,
      ]);
    }

    if (tracking.upstreamMergeRef) {
      await git.raw([
        "config",
        `branch.${branch}.merge`,
        tracking.upstreamMergeRef,
      ]);
    }
  }

  private async resolveBranchRestoreStatus(
    git: GitClient,
    branch: string,
    cloudHead: string,
    localGitState?: HandoffLocalGitState,
  ): Promise<GitBranchRestoreStatus> {
    const branchRef = `refs/heads/${branch}`;
    const branchExists = await this.refExists(git, branchRef);
    if (!branchExists) {
      return { kind: "missing" };
    }

    const currentBranchHead = (await git.revparse([branchRef])).trim();
    const candidateHeads = [
      currentBranchHead,
      ...(localGitState?.branch === branch && localGitState.head
        ? [localGitState.head]
        : []),
    ].filter((value, index, array) => array.indexOf(value) === index);

    if (candidateHeads.every((head) => head === cloudHead)) {
      return { kind: "match" };
    }

    const nonAncestorHead = await this.findNonAncestorHead(
      git,
      candidateHeads,
      cloudHead,
    );
    if (!nonAncestorHead) {
      return { kind: "fast_forward" };
    }

    return {
      kind: "diverged",
      divergence: {
        branch,
        localHead: nonAncestorHead,
        cloudHead,
      },
    };
  }

  private async findNonAncestorHead(
    _git: GitClient,
    heads: string[],
    cloudHead: string,
  ): Promise<string | null> {
    for (const head of heads) {
      if (head === cloudHead) {
        continue;
      }
      if (!(await this.isAncestor(head, cloudHead))) {
        return head;
      }
    }
    return null;
  }

  private async checkoutBranchAtHead(
    git: GitClient,
    branch: string,
    head: string,
  ): Promise<void> {
    const currentBranch = await getCurrentBranchName(git);
    if (currentBranch === branch) {
      await git.reset(["--hard", head]);
      return;
    }

    const branchRef = `refs/heads/${branch}`;
    if (await this.refExists(git, branchRef)) {
      await git.branch(["-f", branch, head]);
      await git.checkout(branch);
      return;
    }

    await git.checkout(["-b", branch, head]);
  }

  private async refExists(git: GitClient, ref: string): Promise<boolean> {
    try {
      await git.revparse(["--verify", ref]);
      return true;
    } catch {
      return false;
    }
  }

  private async isAncestor(
    ancestor: string,
    descendant: string,
  ): Promise<boolean> {
    const exitCode = await this.runGitProcessAllowingFailure([
      "merge-base",
      "--is-ancestor",
      ancestor,
      descendant,
    ]);
    return exitCode === 0;
  }

  private async createTempDir(
    git: GitClient,
    checkpointId: string,
  ): Promise<string> {
    // Git stages packs in the object store, so the destination must share its filesystem.
    const gitCommonDir = await this.resolveGitCommonDir(git);
    return mkdtemp(
      path.join(gitCommonDir, `posthog-code-handoff-${checkpointId}-`),
    );
  }

  private async resolveGitCommonDir(git: GitClient): Promise<string> {
    const raw = await git.raw([
      "rev-parse",
      "--path-format=absolute",
      "--git-common-dir",
    ]);
    const resolved = raw.trim() || ".git";
    return path.isAbsolute(resolved)
      ? resolved
      : path.resolve(this.repositoryPath, resolved);
  }

  private async getGitPath(git: GitClient, gitPath: string): Promise<string> {
    const raw = await git.raw(["rev-parse", "--git-path", gitPath]);
    const resolved = raw.trim();
    return path.isAbsolute(resolved)
      ? resolved
      : path.resolve(this.repositoryPath, resolved);
  }

  private async getFileSize(filePath: string): Promise<number> {
    return (await stat(filePath)).size;
  }

  private async runGitWithInput(
    args: string[],
    input: string,
  ): Promise<string> {
    const { stdout } = await this.runGitProcess(args, input);
    return stdout;
  }

  private async runGitWithBuffer(args: string[], input: Buffer): Promise<void> {
    await this.runGitProcess(args, input);
  }

  private async runGitProcessAllowingFailure(args: string[]): Promise<number> {
    return new Promise((resolve, reject) => {
      const child = spawn("git", args, {
        cwd: this.repositoryPath,
        stdio: ["ignore", "ignore", "pipe"],
      });

      let stderr = "";
      child.stderr.on("data", (chunk: Buffer | string) => {
        stderr += chunk.toString();
      });
      child.on("error", reject);
      child.on("close", (code) => {
        if (code === null) {
          reject(new Error(`git ${args.join(" ")} exited unexpectedly`));
          return;
        }
        if (code > 1) {
          reject(
            new Error(
              stderr || `git ${args.join(" ")} failed with code ${code}`,
            ),
          );
          return;
        }
        resolve(code);
      });
    });
  }

  private async runGitWithEnv(
    env: NodeJS.ProcessEnv,
    args: string[],
  ): Promise<string> {
    return new Promise((resolve, reject) => {
      const child = spawn("git", args, {
        cwd: this.repositoryPath,
        stdio: ["ignore", "pipe", "pipe"],
        env,
      });
      let stdout = "";
      let stderr = "";
      child.stdout.on("data", (chunk: Buffer | string) => {
        stdout += chunk.toString();
      });
      child.stderr.on("data", (chunk: Buffer | string) => {
        stderr += chunk.toString();
      });
      child.on("error", reject);
      child.on("close", (code) => {
        if (code === 0) {
          resolve(stdout);
          return;
        }
        reject(
          new Error(stderr || `git ${args.join(" ")} failed with code ${code}`),
        );
      });
    });
  }

  private runGitProcess(
    args: string[],
    input: string | Buffer,
  ): Promise<{ stdout: string; stderr: string }> {
    return new Promise((resolve, reject) => {
      const child = spawn("git", args, {
        cwd: this.repositoryPath,
        stdio: "pipe",
      });

      let stdout = "";
      let stderr = "";

      child.stdout.on("data", (chunk: Buffer | string) => {
        stdout += chunk.toString();
      });
      child.stderr.on("data", (chunk: Buffer | string) => {
        stderr += chunk.toString();
      });
      child.on("error", reject);
      child.on("close", (code) => {
        if (code === 0) {
          resolve({ stdout, stderr });
          return;
        }
        reject(
          new Error(stderr || `git ${args.join(" ")} failed with code ${code}`),
        );
      });

      child.stdin.on("error", () => {});
      child.stdin.end(input);
    });
  }
}

export async function readHandoffLocalGitState(
  repositoryPath: string,
): Promise<HandoffLocalGitState> {
  const git = createGitClient(repositoryPath);
  const head = await readCurrentHead(git);
  const branch = await getCurrentBranchName(git);
  const tracking = await getTrackingMetadata(git, branch);

  if (tracking.upstreamRemote && tracking.upstreamMergeRef) {
    await git
      .raw(["fetch", tracking.upstreamRemote, tracking.upstreamMergeRef])
      .catch(() => {});
  }

  const upstreamHead =
    tracking.upstreamRemote && tracking.upstreamMergeRef
      ? await resolveUpstreamHead(
          git,
          tracking.upstreamRemote,
          tracking.upstreamMergeRef,
        )
      : null;

  return {
    head,
    branch,
    upstreamHead,
    upstreamRemote: tracking.upstreamRemote,
    upstreamMergeRef: tracking.upstreamMergeRef,
  };
}

async function readCurrentHead(git: GitClient): Promise<string | null> {
  try {
    return (await git.revparse(["HEAD"])).trim() || null;
  } catch {
    return null;
  }
}

async function getCurrentBranchName(git: GitClient): Promise<string | null> {
  try {
    const raw = await git.revparse(["--abbrev-ref", "HEAD"]);
    const branch = raw.trim();
    return branch === "HEAD" ? null : branch;
  } catch {
    return null;
  }
}

async function getTrackingMetadata(
  git: GitClient,
  branch: string | null,
): Promise<GitTrackingMetadata> {
  if (!branch) {
    return {
      upstreamRemote: null,
      upstreamMergeRef: null,
      remoteUrl: null,
    };
  }

  const upstreamRemote = await getGitConfigValue(
    git,
    `branch.${branch}.remote`,
  );
  const upstreamMergeRef = await getGitConfigValue(
    git,
    `branch.${branch}.merge`,
  );
  const remoteUrl = upstreamRemote
    ? await getRemoteUrl(git, upstreamRemote)
    : null;

  return { upstreamRemote, upstreamMergeRef, remoteUrl };
}

async function getGitConfigValue(
  git: GitClient,
  key: string,
): Promise<string | null> {
  try {
    const value = await git.raw(["config", "--get", key]);
    return value.trim() || null;
  } catch {
    return null;
  }
}

async function getRemoteUrl(
  git: GitClient,
  remote: string,
): Promise<string | null> {
  try {
    const value = await git.remote(["get-url", remote]);
    return typeof value === "string" ? value.trim() || null : null;
  } catch {
    return null;
  }
}

async function resolveUpstreamHead(
  git: GitClient,
  upstreamRemote: string,
  upstreamMergeRef: string,
): Promise<string | null> {
  const upstreamBranch = upstreamMergeRef.replace("refs/heads/", "");
  try {
    return (
      (await git.revparse([`${upstreamRemote}/${upstreamBranch}`])).trim() ||
      null
    );
  } catch {
    return null;
  }
}

function hasTrackingConfig(
  localGitState: HandoffLocalGitState | undefined,
): boolean {
  return !!(localGitState?.upstreamRemote || localGitState?.upstreamMergeRef);
}
