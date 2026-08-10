// Namespace import (not `{ execFile }`) so the renderer's browser bundle can
// resolve this node-only module against vite's `__vite-browser-external` stub,
// which has no named exports. This module never runs in the browser.
import * as childProcess from "node:child_process";
import * as crypto from "node:crypto";
import * as fs from "node:fs";
import * as path from "node:path";
import { mapWithConcurrency } from "./concurrency";
import { execGh, execGhWithRetry, type GhExecResult } from "./gh";
import { buildPostHogTrailers } from "./trailers";
import { parseGithubUrl } from "./utils";

/**
 * Creates GitHub-signed ("Verified") commits without any local signing key, by
 * sending the staged changes through GitHub's GraphQL `createCommitOnBranch`
 * mutation. The mutation authors and signs the commit as the identity that owns
 * the token, so cloud-agent commits satisfy signed-commit branch protection.
 *
 * This is the deterministic replacement for the prompt-driven `gh api graphql`
 * flow: it passes the `FileChanges` payload as a real GraphQL object (not a
 * string scalar), fetches the branch tip so multi-commit diffs work, chunks
 * oversized payloads, and keeps the local checkout pointed at the new commit.
 */

const DEFAULT_MAX_PAYLOAD_BYTES = 35 * 1024 * 1024;
const MAX_GIT_BUFFER = 256 * 1024 * 1024;
// Per-attempt cap for the GraphQL commit call; retried with backoff on timeout.
const GH_GRAPHQL_TIMEOUT_MS = 30_000;

export interface SignedCommitCtx {
  /** Working directory of the clone. */
  cwd: string;
  /** GitHub token used for the mutation; determines the signed author identity. */
  token: string;
  /** Appended as a `Task-Id` trailer when present. */
  taskId?: string;
  /**
   * Branch the tool refuses to commit directly onto. Defaults to the remote's
   * default branch (`origin/HEAD`), so an accidental commit straight onto `main`
   * is blocked even without an explicit value.
   */
  baseBranch?: string;
}

export interface SignedCommitInput {
  /** Commit headline (first line). */
  message: string;
  /** Optional extended body; PostHog trailers are appended automatically. */
  body?: string;
  /** Target branch; defaults to the current branch. Created on the remote if missing. */
  branch?: string;
  /** Files to stage before committing; defaults to whatever is already staged. */
  paths?: string[];
}

export interface SignedCommitResult {
  branch: string;
  /** Repository the commits were pushed to, as `owner/repo` (from the origin remote). */
  repository: string;
  /** One entry per chunk; >1 only when the payload was split. */
  commits: { sha: string; url: string }[];
}

export interface SignedRewriteInput {
  branch?: string;
  onto?: string;
}

export class OversizedFileError extends Error {
  constructor(
    readonly path: string,
    readonly bytes: number,
    readonly maxBytes: number,
  ) {
    super(
      `File '${path}' (~${Math.round(bytes / 1024 / 1024)}MB once base64-encoded) ` +
        `exceeds the per-commit request limit (~${Math.round(maxBytes / 1024 / 1024)}MB). ` +
        `A single file cannot be split across createCommitOnBranch requests; use Git LFS ` +
        `or a local signing key for this change.`,
    );
    this.name = "OversizedFileError";
  }
}

interface FileAddition {
  path: string;
  contents: string;
}
interface FileDeletion {
  path: string;
}
interface FileChanges {
  additions: FileAddition[];
  deletions: FileDeletion[];
}

interface GitRunResult {
  stdout: Buffer;
  stderr: string;
  exitCode: number;
}

function runGit(args: string[], cwd: string): Promise<GitRunResult> {
  return new Promise((resolve) => {
    childProcess.execFile(
      "git",
      args,
      { cwd, maxBuffer: MAX_GIT_BUFFER, encoding: "buffer" },
      (error, stdout, stderr) => {
        const err = error as (Error & { code?: number | string }) | null;
        const exitCode =
          err && typeof err.code === "number" ? err.code : err ? 1 : 0;
        resolve({
          stdout: (stdout as unknown as Buffer) ?? Buffer.alloc(0),
          stderr: ((stderr as unknown as Buffer) ?? Buffer.alloc(0)).toString(
            "utf8",
          ),
          exitCode,
        });
      },
    );
  });
}

async function gitText(args: string[], cwd: string): Promise<string> {
  const r = await runGit(args, cwd);
  if (r.exitCode !== 0) {
    throw new Error(`git ${args.join(" ")} failed: ${r.stderr.trim()}`);
  }
  return r.stdout.toString("utf8").trim();
}

/** Conflicted/multi-parent git operation that may be mid-flight in a checkout. */
export type GitOperationInProgress = "merge" | "rebase" | "cherry-pick";

const OPERATION_MARKERS: readonly [string, GitOperationInProgress][] = [
  ["MERGE_HEAD", "merge"],
  ["CHERRY_PICK_HEAD", "cherry-pick"],
  ["rebase-merge", "rebase"],
  ["rebase-apply", "rebase"],
];

async function detectOperationInProgress(
  cwd: string,
): Promise<GitOperationInProgress | null> {
  // `--git-path` resolves the marker locations correctly inside worktrees,
  // returning paths relative to the process cwd.
  const out = await gitText(
    [
      "rev-parse",
      ...OPERATION_MARKERS.flatMap(([marker]) => ["--git-path", marker]),
    ],
    cwd,
  );
  const markerPaths = out.split("\n");
  for (let i = 0; i < OPERATION_MARKERS.length; i++) {
    const markerPath = markerPaths[i];
    if (markerPath && fs.existsSync(path.resolve(cwd, markerPath))) {
      return OPERATION_MARKERS[i][1];
    }
  }
  return null;
}

/** Agent-facing refusal for publishing while a git operation is mid-flight. */
export function operationInProgressError(op: GitOperationInProgress): string {
  if (op === "merge") {
    return (
      "A merge is in progress (MERGE_HEAD exists). Commits are published via GitHub's " +
      "createCommitOnBranch API, which can only create single-parent commits — committing " +
      "a staged merge would LINEARIZE it, attributing every base-branch change since the " +
      "branch point to this PR (this is how PRs balloon to 100k+ changed lines). " +
      "Recovery: run `git merge --abort`, then either call `git_signed_merge` to merge the " +
      "base branch server-side (clean merges), or run `git rebase origin/<base>`, resolve " +
      "conflicts, finish with `git rebase --continue`, and call `git_signed_rewrite`."
    );
  }
  if (op === "rebase") {
    return (
      "A rebase is in progress. Finish it first — resolve conflicts, `git add` the files, " +
      "then `git rebase --continue` (or back out with `git rebase --abort`) — and publish " +
      "the rebased branch with `git_signed_rewrite`."
    );
  }
  return (
    "A cherry-pick is in progress. Finish it first with `git cherry-pick --continue` " +
    "(or back out with `git cherry-pick --abort`), then retry."
  );
}

async function resolveRepoNameWithOwner(ctx: SignedCommitCtx): Promise<string> {
  const url = await gitText(["remote", "get-url", "origin"], ctx.cwd);
  const parsed = parseGithubUrl(url);
  if (!parsed) {
    throw new Error(`Could not parse owner/repo from origin remote: ${url}`);
  }
  return `${parsed.owner}/${parsed.repo}`;
}

async function resolveBaseBranch(ctx: SignedCommitCtx): Promise<string | null> {
  if (ctx.baseBranch) return ctx.baseBranch;
  // Fall back to the remote's default branch so the guard still fires when no
  // explicit base is supplied. Best-effort: a clone without origin/HEAD just
  // leaves the guard inactive rather than failing the commit.
  const r = await runGit(
    ["symbolic-ref", "--short", "refs/remotes/origin/HEAD"],
    ctx.cwd,
  );
  if (r.exitCode !== 0) return null;
  return (
    r.stdout
      .toString("utf8")
      .trim()
      .replace(/^origin\//, "") || null
  );
}

async function resolveBranchName(
  ctx: SignedCommitCtx,
  input: SignedCommitInput,
): Promise<string> {
  const branch = input.branch
    ? input.branch.replace(/^refs\/heads\//, "")
    : await resolveCurrentBranch(ctx);

  // Guard both paths: an explicit `branch: "main"` must be refused the same as
  // landing on the base branch implicitly via HEAD.
  const baseBranch = await resolveBaseBranch(ctx);
  if (baseBranch && branch === baseBranch) {
    throw new Error(
      `Refusing to commit directly to base branch '${baseBranch}'. ` +
        `Pass a 'branch' name prefixed with posthog-code/.`,
    );
  }
  return branch;
}

async function resolveCurrentBranch(ctx: SignedCommitCtx): Promise<string> {
  const current = await gitText(["rev-parse", "--abbrev-ref", "HEAD"], ctx.cwd);
  if (!current || current === "HEAD") {
    throw new Error(
      "Detached HEAD — pass a `branch` to git_signed_commit (e.g. posthog-code/...).",
    );
  }
  return current;
}

async function remoteTip(
  ctx: SignedCommitCtx,
  branch: string,
): Promise<string | null> {
  const out = await gitText(
    ["ls-remote", "--heads", "origin", branch],
    ctx.cwd,
  );
  if (!out) return null;
  return out.split("\t")[0]?.trim() || null;
}

/** Agent-facing refusal when the remote branch has advanced past the local checkout. */
export function behindRemoteError(branch: string, tip: string): string {
  const shortTip = tip.slice(0, 12);
  return (
    `Refusing to commit: remote branch '${branch}' has advanced past your local checkout ` +
    `(remote tip ${shortTip} is not in your local history). Something pushed to the branch ` +
    `after your last commit — often CI automation that auto-commits regenerated artifacts ` +
    `(codegen, lockfiles, formatting) onto open PRs, or another collaborator. Committing now ` +
    `would build the new commit on the remote tip while taking file contents from your stale ` +
    `tree, silently REVERTING those commits. Recovery (preserves your uncommitted work): ` +
    `\`git stash --include-untracked\`, then \`git fetch origin ${branch}\` and ` +
    `\`git reset --hard origin/${branch}\`, then \`git stash pop\` — resolve any pop conflicts, ` +
    `as they mark real overlaps with the new commits — then re-stage and retry ` +
    `git_signed_commit. The hard reset is safe here: your work is saved in the stash, and only ` +
    `a hard reset pulls the new commits' files into your working tree (a soft/mixed reset would ` +
    `keep your stale copies and re-commit the revert). If you were integrating the base branch, ` +
    `use git_signed_merge / git_signed_rewrite instead.`
  );
}

/**
 * Refuse when the remote `tip` has commits the local checkout lacks: the commit
 * builds on `tip` but takes file contents from the index (based on local HEAD),
 * so the staged diff would re-express every remotely-changed file as its stale
 * local blob, silently reverting them. No-op on an unborn HEAD or an
 * unresolvable relationship, so a missing object never blocks a real commit.
 * Caller must have fetched `tip` first.
 */
export async function assertNotBehindRemote(
  ctx: SignedCommitCtx,
  branch: string,
  tip: string,
): Promise<void> {
  const head = await runGit(["rev-parse", "HEAD"], ctx.cwd);
  if (head.exitCode !== 0) return;
  if (head.stdout.toString("utf8").trim() === tip) return;
  // exit 1 ⇒ tip not reachable from HEAD ⇒ remote has commits we lack ⇒ refuse.
  const reachable = await runGit(
    ["merge-base", "--is-ancestor", tip, "HEAD"],
    ctx.cwd,
  );
  if (reachable.exitCode === 1) {
    throw new Error(behindRemoteError(branch, tip));
  }
}

async function refApi(
  ctx: SignedCommitCtx,
  args: string[],
  errLabel: string,
): Promise<void> {
  const res = await execGh(args, { cwd: ctx.cwd, env: ghTokenEnv(ctx.token) });
  if (res.exitCode !== 0) {
    throw new Error(`${errLabel}: ${res.stderr || res.error}`);
  }
}

function createRef(
  ctx: SignedCommitCtx,
  repo: string,
  branch: string,
  sha: string,
): Promise<void> {
  return refApi(
    ctx,
    [
      "api",
      "-X",
      "POST",
      `/repos/${repo}/git/refs`,
      "-f",
      `ref=refs/heads/${branch}`,
      "-f",
      `sha=${sha}`,
    ],
    `Failed to create branch '${branch}'`,
  );
}

/**
 * Fast-forward-only ref update: GitHub rejects a non-fast-forward PATCH
 * without `force`, so a concurrently moved branch fails safely instead of
 * being clobbered.
 */
function fastForwardRef(
  ctx: SignedCommitCtx,
  repo: string,
  branch: string,
  sha: string,
): Promise<void> {
  return refApi(
    ctx,
    [
      "api",
      "-X",
      "PATCH",
      `/repos/${repo}/git/refs/heads/${branch}`,
      "-f",
      `sha=${sha}`,
    ],
    `Failed to fast-forward '${branch}'`,
  );
}

function forceUpdateRef(
  ctx: SignedCommitCtx,
  repo: string,
  branch: string,
  sha: string,
): Promise<void> {
  return refApi(
    ctx,
    [
      "api",
      "-X",
      "PATCH",
      `/repos/${repo}/git/refs/heads/${branch}`,
      "-f",
      `sha=${sha}`,
      "-F",
      "force=true",
    ],
    `Failed to force-update '${branch}'`,
  );
}

function deleteRef(
  ctx: SignedCommitCtx,
  repo: string,
  branch: string,
): Promise<void> {
  return refApi(
    ctx,
    ["api", "-X", "DELETE", `/repos/${repo}/git/refs/heads/${branch}`],
    `Failed to delete ref '${branch}'`,
  );
}

/** Env var names the GitHub CLI / git credential helper read a token from, in order. */
export const GITHUB_TOKEN_ENV_VARS = ["GH_TOKEN", "GITHUB_TOKEN"] as const;

/** First GitHub token found in `env` (defaults to the process env), if any. */
export function readGithubTokenFromEnv(
  env: Record<string, string | undefined> = process.env,
): string | undefined {
  for (const name of GITHUB_TOKEN_ENV_VARS) {
    if (env[name]) return env[name];
  }
  return undefined;
}

export function ghTokenEnv(token: string): Record<string, string> {
  return Object.fromEntries(GITHUB_TOKEN_ENV_VARS.map((name) => [name, token]));
}

// Concurrency for staged-blob reads; bounds spawned `git show` processes while
// still cutting wall-clock for multi-file commits.
const STAGED_READ_CONCURRENCY = 16;

// Turns a `--name-status -z` diff into the `FileChanges` payload, reading each
// added/modified file's new blob via `readBlob`
async function readChangesFromDiff(
  ctx: SignedCommitCtx,
  diffArgs: string[],
  readBlob: (path: string) => string[],
): Promise<FileChanges> {
  const diff = await runGit(diffArgs, ctx.cwd);
  if (diff.exitCode !== 0) {
    throw new Error(`git ${diffArgs.join(" ")} failed: ${diff.stderr.trim()}`);
  }
  const tokens = diff.stdout.toString("utf8").split("\0").filter(Boolean);

  const addPaths: string[] = [];
  const deletions: FileDeletion[] = [];
  for (let i = 0; i + 1 < tokens.length; i += 2) {
    const path = tokens[i + 1];
    if (tokens[i].startsWith("D")) {
      deletions.push({ path });
    } else {
      addPaths.push(path);
    }
  }

  const additions = await mapWithConcurrency(
    addPaths,
    STAGED_READ_CONCURRENCY,
    async (path) => {
      const r = await runGit(readBlob(path), ctx.cwd);
      if (r.exitCode !== 0) {
        throw new Error(`Failed to read file '${path}': ${r.stderr.trim()}`);
      }
      return { path, contents: r.stdout.toString("base64") };
    },
  );
  return { additions, deletions };
}

function buildFileChanges(
  ctx: SignedCommitCtx,
  baseOid: string,
): Promise<FileChanges> {
  // Read the *staged* blob (`:path`) so we commit exactly what was staged, not
  // any later unstaged edits in the working tree.
  return readChangesFromDiff(
    ctx,
    ["diff", "--cached", "-z", "--no-renames", "--name-status", baseOid],
    (path) => ["show", `:${path}`],
  );
}

// The change between two arbitrary commits/trees, reading the new blob from the
// `to` side. Used by the rewrite path to replay one commit's net diff at a time.
function buildFileChangesBetween(
  ctx: SignedCommitCtx,
  fromOid: string,
  toOid: string,
): Promise<FileChanges> {
  return readChangesFromDiff(
    ctx,
    ["diff", "-z", "--no-renames", "--name-status", fromOid, toOid],
    (path) => ["show", `${toOid}:${path}`],
  );
}

function additionBytes(a: FileAddition): number {
  // base64 contents dominate; add path + per-entry JSON envelope overhead.
  return a.contents.length + a.path.length + 32;
}

export function chunkFileChanges(
  changes: FileChanges,
  maxBytes: number,
): FileChanges[] {
  for (const a of changes.additions) {
    const bytes = additionBytes(a);
    if (bytes > maxBytes) throw new OversizedFileError(a.path, bytes, maxBytes);
  }

  if (changes.additions.length === 0) {
    return [{ additions: [], deletions: changes.deletions }];
  }

  const chunks: FileChanges[] = [];
  // Deletions are path-only (negligible); put them all in the first chunk.
  let cur: FileChanges = { additions: [], deletions: [...changes.deletions] };
  let curBytes = changes.deletions.reduce((n, d) => n + d.path.length + 16, 0);

  for (const a of changes.additions) {
    const bytes = additionBytes(a);
    if (cur.additions.length > 0 && curBytes + bytes > maxBytes) {
      chunks.push(cur);
      cur = { additions: [], deletions: [] };
      curBytes = 0;
    }
    cur.additions.push(a);
    curBytes += bytes;
  }
  chunks.push(cur);
  return chunks;
}

/** One entry of `git diff-index` / `git diff-tree` raw `-z` output. */
export interface RawDiffEntry {
  path: string;
  oldOid: string;
  /** All-zeros for deletions (and for an unmerged/dirty index entry). */
  newOid: string;
  /** Status letter: A/M/D/T/U… (`--no-renames` rules out two-path R/C entries). */
  status: string;
}

/** Parses raw `-z` diff output: `:<oldmode> <newmode> <oldoid> <newoid> <status>\0<path>\0…` */
export function parseRawDiffZ(text: string): RawDiffEntry[] {
  const tokens = text.split("\0");
  const entries: RawDiffEntry[] = [];
  for (let i = 0; i + 1 < tokens.length; i += 2) {
    const meta = tokens[i];
    if (!meta.startsWith(":")) continue;
    const fields = meta.slice(1).split(" ");
    if (fields.length < 5) continue;
    entries.push({
      path: tokens[i + 1],
      oldOid: fields[2],
      newOid: fields[3],
      status: fields[4],
    });
  }
  return entries;
}

/**
 * Staged files that would copy base-branch content into the PR: not part of
 * the PR's existing diff, and staged with exactly the blob the base tip has
 * (matching all-zero OIDs make a staged deletion of a base-deleted file a
 * leak too, while PR-authored deletions of base-untouched files pass).
 */
export function detectBaseLeaks(
  staged: readonly RawDiffEntry[],
  prFiles: ReadonlySet<string>,
  baseChanged: ReadonlyMap<string, string>,
): string[] {
  return staged
    .filter((e) => !prFiles.has(e.path) && baseChanged.get(e.path) === e.newOid)
    .map((e) => e.path);
}

const LEAK_SAMPLE_SIZE = 10;

/**
 * Hard gate against the mass-file-leak failure: a botched base-branch merge
 * staged for `git_signed_commit` attributes every base-side change to the PR.
 * Best-effort like `syncLocalCheckout` — environments where the base can't be
 * resolved (no origin/HEAD, failed fetch, shallow history without a merge
 * base) skip the check with a warning rather than blocking the commit.
 */
async function assertNoBaseLeak(
  ctx: SignedCommitCtx,
  branch: string,
  tip: string,
): Promise<void> {
  const skip = (reason: string) => {
    process.stderr.write(
      `[signed-commit] base-leak check skipped: ${reason}\n`,
    );
  };

  const base = await resolveBaseBranch(ctx);
  if (!base || base === branch) return;

  const fetched = await runGit(["fetch", "--no-tags", "origin", base], ctx.cwd);
  if (fetched.exitCode !== 0) {
    return skip(`fetch origin/${base} failed: ${fetched.stderr.trim()}`);
  }
  const baseTipRes = await runGit(
    ["rev-parse", `refs/remotes/origin/${base}^{commit}`],
    ctx.cwd,
  );
  if (baseTipRes.exitCode !== 0) {
    return skip(`could not resolve origin/${base}`);
  }
  const baseTip = baseTipRes.stdout.toString("utf8").trim();

  const mergeBaseRes = await runGit(["merge-base", baseTip, tip], ctx.cwd);
  if (mergeBaseRes.exitCode !== 0) {
    return skip(
      `no merge base between origin/${base} and ${tip.slice(0, 12)} (shallow clone?)`,
    );
  }
  const mergeBase = mergeBaseRes.stdout.toString("utf8").trim();
  if (mergeBase === baseTip) return; // branch already contains the base tip

  // Three metadata-only diffs (no content reads), so this stays fast even on
  // very large repos. Plumbing output uses full blob OIDs, safe to compare.
  const [stagedRaw, prNames, baseRaw] = await Promise.all([
    gitText(["diff-index", "--cached", "-z", "--no-renames", tip], ctx.cwd),
    gitText(
      ["diff-tree", "-r", "-z", "--name-only", "--no-renames", mergeBase, tip],
      ctx.cwd,
    ),
    gitText(
      ["diff-tree", "-r", "-z", "--no-renames", mergeBase, baseTip],
      ctx.cwd,
    ),
  ]);

  const leaks = detectBaseLeaks(
    parseRawDiffZ(stagedRaw),
    new Set(prNames.split("\0").filter(Boolean)),
    new Map(parseRawDiffZ(baseRaw).map((e) => [e.path, e.newOid])),
  );
  if (leaks.length === 0) return;

  const sample = leaks.slice(0, LEAK_SAMPLE_SIZE).join("\n  ");
  const more =
    leaks.length > LEAK_SAMPLE_SIZE
      ? `\n  …and ${leaks.length - LEAK_SAMPLE_SIZE} more`
      : "";
  throw new Error(
    `Refusing to commit: ${leaks.length} staged file(s) exactly match origin/${base} ` +
      "content but are not part of this PR's diff — committing them would copy " +
      "base-branch changes into the PR (the mass-file-leak failure). This usually means " +
      `a merge from the base branch was staged. Leaked files:\n  ${sample}${more}\n` +
      "Recovery: unstage everything (`git reset`), restore base-owned files from the " +
      "branch tip (`git checkout <tip> -- <paths>`), re-stage only the files you actually " +
      "changed, and retry. To bring the base branch into the PR, call `git_signed_merge` " +
      "instead.",
  );
}

const CREATE_COMMIT_MUTATION = `mutation($input: CreateCommitOnBranchInput!) {
  createCommitOnBranch(input: $input) { commit { oid url } }
}`;

async function createCommitOnBranch(
  ctx: SignedCommitCtx,
  repo: string,
  branch: string,
  expectedHeadOid: string,
  headline: string,
  body: string,
  changes: FileChanges,
): Promise<{ oid: string; url: string }> {
  const payload = JSON.stringify({
    query: CREATE_COMMIT_MUTATION,
    variables: {
      input: {
        branch: { repositoryNameWithOwner: repo, branchName: branch },
        expectedHeadOid,
        message: { headline, body },
        fileChanges: changes,
      },
    },
  });

  const res = await execGhWithRetry(
    ["api", "graphql", "--input", "-"],
    {
      cwd: ctx.cwd,
      input: payload,
      env: ghTokenEnv(ctx.token),
      // Bound each attempt so a stalled connection can't hang the tool forever.
      timeoutMs: GH_GRAPHQL_TIMEOUT_MS,
    },
    { maxAttempts: 3 },
  );
  if (res.exitCode !== 0) {
    throw new Error(
      `createCommitOnBranch failed: ${res.stderr || res.error || res.stdout}`,
    );
  }

  let parsed: {
    data?: { createCommitOnBranch?: { commit?: { oid: string; url: string } } };
    errors?: unknown;
  };
  try {
    parsed = JSON.parse(res.stdout);
  } catch {
    throw new Error(
      `createCommitOnBranch returned non-JSON: ${res.stdout.slice(0, 500)}`,
    );
  }
  if (parsed.errors) {
    throw new Error(
      `createCommitOnBranch errors: ${JSON.stringify(parsed.errors)}`,
    );
  }
  const commit = parsed.data?.createCommitOnBranch?.commit;
  if (!commit?.oid) {
    throw new Error(`createCommitOnBranch returned no commit: ${res.stdout}`);
  }
  return commit;
}

async function syncLocalCheckout(
  ctx: SignedCommitCtx,
  branch: string,
  newOid: string,
): Promise<void> {
  // Fetch the new tip object, point the local branch + HEAD at it, and reset
  // the index — all without touching the working tree, so unstaged work the
  // agent intends for a later commit is preserved. Best-effort: the commit is
  // already on the remote, and the next call re-resolves the tip via ls-remote,
  // so a sync failure isn't fatal — but warn rather than swallow it silently,
  // since a stale local checkout is otherwise painful to diagnose.
  const steps: [string, string[]][] = [
    ["fetch", ["fetch", "--no-tags", "origin", branch]],
    ["update-ref", ["update-ref", `refs/heads/${branch}`, newOid]],
    ["symbolic-ref", ["symbolic-ref", "HEAD", `refs/heads/${branch}`]],
    ["reset", ["reset", "-q"]],
  ];
  for (const [label, args] of steps) {
    const r = await runGit(args, ctx.cwd);
    if (r.exitCode !== 0) {
      process.stderr.write(
        `[signed-commit] local sync step '${label}' failed after committing ${newOid}: ${r.stderr.trim()}\n`,
      );
    }
  }
}

async function publishChunks(
  ctx: SignedCommitCtx,
  repo: string,
  branch: string,
  baseOid: string,
  headline: string,
  body: string,
  chunks: FileChanges[],
): Promise<{ commits: { sha: string; url: string }[]; tip: string }> {
  const commits: { sha: string; url: string }[] = [];
  let tip = baseOid;
  for (let i = 0; i < chunks.length; i++) {
    const hl =
      chunks.length > 1
        ? `${headline} — part ${i + 1}/${chunks.length}`
        : headline;
    const commit = await createCommitOnBranch(
      ctx,
      repo,
      branch,
      tip,
      hl,
      body,
      chunks[i],
    );
    commits.push({ sha: commit.oid, url: commit.url });
    tip = commit.oid;
  }
  return { commits, tip };
}

function publishChanges(
  ctx: SignedCommitCtx,
  repo: string,
  branch: string,
  baseOid: string,
  headline: string,
  body: string,
  changes: FileChanges,
): Promise<{ commits: { sha: string; url: string }[]; tip: string }> {
  const chunks = chunkFileChanges(changes, DEFAULT_MAX_PAYLOAD_BYTES);
  return publishChunks(ctx, repo, branch, baseOid, headline, body, chunks);
}

/**
 * Like `publishChanges`, but a payload split across multiple commits is
 * published to a scratch ref first and the real branch only moves once all
 * chunks landed — a mid-flight failure can't leave partial "part i/n" commits
 * on the branch. Single-chunk commits keep the direct fast path.
 */
async function publishChangesAtomic(
  ctx: SignedCommitCtx,
  repo: string,
  branch: string,
  baseOid: string,
  headline: string,
  body: string,
  changes: FileChanges,
): Promise<{ commits: { sha: string; url: string }[]; tip: string }> {
  const chunks = chunkFileChanges(changes, DEFAULT_MAX_PAYLOAD_BYTES);
  if (chunks.length === 1) {
    return publishChunks(ctx, repo, branch, baseOid, headline, body, chunks);
  }

  const scratch = `posthog-code/commit-tmp/${crypto.randomUUID()}`;
  await createRef(ctx, repo, scratch, baseOid);
  try {
    const published = await publishChunks(
      ctx,
      repo,
      scratch,
      baseOid,
      headline,
      body,
      chunks,
    );
    // The chunk chain grew from `baseOid` (the branch tip we read), so this is
    // a fast-forward; it fails safely if the branch moved meanwhile.
    await fastForwardRef(ctx, repo, branch, published.tip);
    return published;
  } finally {
    await deleteRef(ctx, repo, scratch).catch(() => {});
  }
}

export async function createSignedCommit(
  ctx: SignedCommitCtx,
  input: SignedCommitInput,
): Promise<SignedCommitResult> {
  // Refuse before touching the index: a staged merge/rebase/cherry-pick must
  // never reach createCommitOnBranch, which would linearize it.
  const op = await detectOperationInProgress(ctx.cwd);
  if (op) {
    throw new Error(operationInProgressError(op));
  }

  // Repo (from origin remote) and branch (from HEAD) are independent reads.
  const [repo, branch] = await Promise.all([
    resolveRepoNameWithOwner(ctx),
    resolveBranchName(ctx, input),
  ]);

  if (input.paths && input.paths.length > 0) {
    const r = await runGit(["add", "--", ...input.paths], ctx.cwd);
    if (r.exitCode !== 0) {
      throw new Error(`git add failed: ${r.stderr.trim()}`);
    }
  }

  let tip = await remoteTip(ctx, branch);
  if (tip === null) {
    // New branch: create it from the local HEAD, which is already present —
    // no fetch needed to diff against it.
    const baseSha = await gitText(["rev-parse", "HEAD"], ctx.cwd);
    await createRef(ctx, repo, branch, baseSha);
    tip = baseSha;
  } else {
    // Existing branch: make its tip object local so the staged diff (and any
    // later reset) can resolve it.
    await runGit(["fetch", "--no-tags", "origin", branch], ctx.cwd);
    // Committing a stale tree onto an advanced tip would silently revert the
    // commits we never pulled.
    await assertNotBehindRemote(ctx, branch, tip);
  }

  const changes = await buildFileChanges(ctx, tip);
  if (changes.additions.length === 0 && changes.deletions.length === 0) {
    // The staged tree already equals the branch tip. If the index differs from HEAD there ARE
    // staged changes — they're just already present on `branch` — so this is an idempotent
    // no-op, not a "forgot to stage" error. Returning success stops the caller from retrying
    // `git add` against a branch that already has the content.
    const hasStagedChanges =
      (await runGit(["diff", "--cached", "--quiet", "HEAD"], ctx.cwd))
        .exitCode !== 0;
    if (hasStagedChanges) {
      return { branch, repository: repo, commits: [] };
    }
    throw new Error(
      "No staged changes to commit. Stage files with `git add` first (or pass `paths`).",
    );
  }

  await assertNoBaseLeak(ctx, branch, tip);

  const body = [input.body, buildPostHogTrailers(ctx.taskId).join("\n")]
    .filter(Boolean)
    .join("\n\n");

  const { commits, tip: newTip } = await publishChangesAtomic(
    ctx,
    repo,
    branch,
    tip,
    input.message,
    body,
    changes,
  );

  await syncLocalCheckout(ctx, branch, newTip);
  return { branch, repository: repo, commits };
}

/** Splits a raw commit message into a headline and the remaining body */
export function splitCommitMessage(raw: string): {
  headline: string;
  body: string;
} {
  const nl = raw.indexOf("\n");
  if (nl === -1) return { headline: raw.trim(), body: "" };
  return {
    headline: raw.slice(0, nl).trim(),
    body: raw
      .slice(nl + 1)
      .replace(/^\n+/, "")
      .trimEnd(),
  };
}

async function resolveOnto(
  ctx: SignedCommitCtx,
  input: SignedRewriteInput,
  baseBranch: string | null,
): Promise<string> {
  if (input.onto) {
    return gitText(["rev-parse", `${input.onto}^{commit}`], ctx.cwd);
  }
  if (!baseBranch) {
    throw new Error(
      "Could not determine the base branch — pass `onto` explicitly (e.g. origin/master).",
    );
  }
  return gitText(["merge-base", `origin/${baseBranch}`, "HEAD"], ctx.cwd);
}

/**
 * Republishes the current local branch as GitHub-signed history and
 * force-updates the remote branch onto it — the signed-commit equivalent of `git push --force`
 */
export async function createSignedRewrite(
  ctx: SignedCommitCtx,
  input: SignedRewriteInput,
): Promise<SignedCommitResult> {
  const [repo, branch] = await Promise.all([
    resolveRepoNameWithOwner(ctx),
    resolveBranchName(ctx, { message: "", branch: input.branch }),
  ]);

  // Rewrite only updates existing history — a brand-new branch goes through
  // createSignedCommit instead.
  const staleTip = await remoteTip(ctx, branch);
  if (staleTip === null) {
    throw new Error(
      `Branch '${branch}' does not exist on the remote. Use git_signed_commit to create it first.`,
    );
  }

  const baseBranch = await resolveBaseBranch(ctx);
  if (baseBranch) {
    await runGit(["fetch", "--no-tags", "origin", baseBranch], ctx.cwd);
  }
  const onto = await resolveOnto(ctx, input, baseBranch);

  // HEAD must descend from `onto` so `onto..HEAD` is exactly the set to replay.
  const ancestry = await runGit(
    ["merge-base", "--is-ancestor", onto, "HEAD"],
    ctx.cwd,
  );
  if (ancestry.exitCode !== 0) {
    throw new Error(
      `Local HEAD is not based on ${onto} — rebase onto the base branch first, then call git_signed_rewrite.`,
    );
  }

  // Replaying first-parent diffs across a local merge folds the entire
  // merged-in branch into one giant commit attributed to this PR.
  const mergeCount = await gitText(
    ["rev-list", "--count", "--merges", `${onto}..HEAD`],
    ctx.cwd,
  );
  if (mergeCount !== "0") {
    throw new Error(
      `Refusing to rewrite: ${onto.slice(0, 12)}..HEAD contains ${mergeCount} merge commit(s), ` +
        "and replaying them would dump every merged-in change (e.g. the whole base branch) " +
        "into this PR. Recovery: `git rebase origin/<base>` (a rebase flattens merges), " +
        "resolve any conflicts, `git rebase --continue`, then retry git_signed_rewrite. " +
        "To simply bring the base branch into the PR, use `git_signed_merge` instead.",
    );
  }

  const list = await gitText(
    ["rev-list", "--reverse", "--first-parent", `${onto}..HEAD`],
    ctx.cwd,
  );
  const localCommits = list ? list.split("\n").filter(Boolean) : [];
  if (localCommits.length === 0) {
    throw new Error(`No commits between ${onto} and HEAD to publish.`);
  }

  const scratch = `posthog-code/rewrite-tmp/${crypto.randomUUID()}`;
  await createRef(ctx, repo, scratch, onto);

  const commits: { sha: string; url: string }[] = [];
  try {
    let expectedHeadOid = onto;
    let prevTree = onto;
    for (const sha of localCommits) {
      const changes = await buildFileChangesBetween(ctx, prevTree, sha);
      prevTree = sha;
      // Skip empty commits (e.g. a merge that's a no-op on the first-parent
      // line) — createCommitOnBranch rejects an empty fileChanges payload.
      if (changes.additions.length === 0 && changes.deletions.length === 0) {
        continue;
      }
      const { headline, body } = splitCommitMessage(
        await gitText(["log", "-1", "--format=%B", sha], ctx.cwd),
      );
      const published = await publishChanges(
        ctx,
        repo,
        scratch,
        expectedHeadOid,
        headline,
        body,
        changes,
      );
      commits.push(...published.commits);
      expectedHeadOid = published.tip;
    }

    if (commits.length === 0) {
      throw new Error(
        "Nothing to publish — every commit was empty after diffing.",
      );
    }

    const currentTip = await remoteTip(ctx, branch);
    if (currentTip !== staleTip) {
      throw new Error(
        `Branch '${branch}' moved while rewriting (expected ${staleTip}, found ${currentTip}). Re-fetch and retry.`,
      );
    }
    await forceUpdateRef(ctx, repo, branch, expectedHeadOid);
    await syncLocalCheckout(ctx, branch, expectedHeadOid);
    return { branch, repository: repo, commits };
  } finally {
    // The history is already published via the ref move; the scratch ref is just
    // bookkeeping, so a delete failure is non-fatal.
    await deleteRef(ctx, repo, scratch).catch(() => {});
  }
}

export interface SignedMergeInput {
  /** PR branch to update; defaults to the current branch. */
  branch?: string;
  /** Branch (or sha) to merge in; defaults to the detected base branch. */
  base?: string;
}

export type SignedMergeResult =
  /** The branch already contained the base (HTTP 204). */
  | { branch: string; base: string; merged: false }
  | {
      branch: string;
      base: string;
      merged: true;
      commit: { sha: string; url: string };
      /** Set when the remote merge succeeded but the local checkout could not be synced. */
      localSyncWarning?: string;
    };

export type MergeApiOutcome =
  | { kind: "merged"; sha: string; url: string }
  | { kind: "up-to-date" }
  | { kind: "conflict" }
  | { kind: "forbidden" }
  | { kind: "error"; message: string };

/** Pure mapping of a `gh api /repos/:repo/merges` result to a merge outcome. */
export function interpretMergeApiResult(res: GhExecResult): MergeApiOutcome {
  if (res.exitCode === 0) {
    const body = res.stdout.trim();
    if (!body) return { kind: "up-to-date" }; // HTTP 204: nothing to merge
    try {
      const parsed = JSON.parse(body) as { sha?: string; html_url?: string };
      if (parsed.sha) {
        return { kind: "merged", sha: parsed.sha, url: parsed.html_url ?? "" };
      }
    } catch {
      // fall through to the generic error below
    }
    return {
      kind: "error",
      message: `unexpected merge response: ${body.slice(0, 300)}`,
    };
  }
  const errText = `${res.stderr} ${res.error ?? ""} ${res.stdout}`;
  if (/HTTP 409/.test(errText)) return { kind: "conflict" };
  if (/HTTP 40[34]/.test(errText)) return { kind: "forbidden" };
  return {
    kind: "error",
    message: (res.stderr || res.error || res.stdout).trim(),
  };
}

/**
 * Merges the base branch INTO the PR branch as a true two-parent merge commit
 * created server-side by GitHub (`POST /repos/{repo}/merges` — the API behind
 * the "Update branch" button), so the commit is GitHub-signed and no history
 * is rewritten. Conflicting merges are refused by GitHub; the caller is
 * directed to the rebase + git_signed_rewrite path instead.
 */
export async function createSignedMerge(
  ctx: SignedCommitCtx,
  input: SignedMergeInput,
): Promise<SignedMergeResult> {
  // A half-finished local merge/rebase would make the post-merge sync land on
  // top of a dirty state; refuse with the same guidance as the commit path.
  const op = await detectOperationInProgress(ctx.cwd);
  if (op) {
    throw new Error(operationInProgressError(op));
  }

  const [repo, branch] = await Promise.all([
    resolveRepoNameWithOwner(ctx),
    resolveBranchName(ctx, { message: "", branch: input.branch }),
  ]);

  const base = input.base ?? (await resolveBaseBranch(ctx));
  if (!base) {
    throw new Error(
      "Could not determine the base branch — pass `base` explicitly (e.g. master).",
    );
  }
  if (base === branch) {
    throw new Error(`Cannot merge '${base}' into itself.`);
  }

  const tip = await remoteTip(ctx, branch);
  if (tip === null) {
    throw new Error(
      `Branch '${branch}' does not exist on the remote. Use git_signed_commit to create it first.`,
    );
  }

  // Only sync the working tree afterwards when it is actually on the target
  // branch — and in that case require it to be clean and published, so the
  // fast-forward below is guaranteed to apply.
  const currentBranch = (
    await runGit(["rev-parse", "--abbrev-ref", "HEAD"], ctx.cwd)
  ).stdout
    .toString("utf8")
    .trim();
  const onTargetBranch = currentBranch === branch;
  if (onTargetBranch) {
    const status = await gitText(
      ["status", "--porcelain", "--untracked-files=no"],
      ctx.cwd,
    );
    if (status) {
      throw new Error(
        "Local checkout has uncommitted changes. Commit them first with git_signed_commit " +
          "(the merge updates the working tree), then retry git_signed_merge.",
      );
    }
    const head = await gitText(["rev-parse", "HEAD"], ctx.cwd);
    if (head !== tip) {
      throw new Error(
        `Local HEAD (${head.slice(0, 12)}) does not match the remote tip of '${branch}' ` +
          `(${tip.slice(0, 12)}). Publish local commits with git_signed_commit (or reset to ` +
          "the remote tip) first, then retry.",
      );
    }
  }

  const message = [
    `Merge branch '${base}' into ${branch}`,
    buildPostHogTrailers(ctx.taskId).join("\n"),
  ]
    .filter(Boolean)
    .join("\n\n");

  const res = await execGhWithRetry(
    [
      "api",
      "-X",
      "POST",
      `/repos/${repo}/merges`,
      "-f",
      `base=${branch}`,
      "-f",
      `head=${base}`,
      "-f",
      `commit_message=${message}`,
    ],
    {
      cwd: ctx.cwd,
      env: ghTokenEnv(ctx.token),
      timeoutMs: GH_GRAPHQL_TIMEOUT_MS,
    },
    { maxAttempts: 3 },
  );

  const outcome = interpretMergeApiResult(res);
  if (outcome.kind === "up-to-date") {
    return { branch, base, merged: false };
  }
  if (outcome.kind === "conflict") {
    throw new Error(
      `Merge conflict between '${base}' and '${branch}' — GitHub cannot auto-merge. ` +
        `Recovery: \`git fetch origin ${base}\`, \`git rebase origin/${base}\`, resolve ` +
        "conflicts, `git rebase --continue`, then call git_signed_rewrite to publish.",
    );
  }
  if (outcome.kind === "forbidden") {
    throw new Error(
      "GitHub refused the merge (HTTP 403/404): the token may lack push access to " +
        `'${branch}', or the repo/branch was not found.`,
    );
  }
  if (outcome.kind === "error") {
    throw new Error(`Merge API failed: ${outcome.message}`);
  }

  // Sync the local checkout with a real fast-forward merge so the working
  // tree gains the base's changes. (`syncLocalCheckout` would keep the old
  // tree, making the merge look like unstaged reversions — staging those
  // would silently undo it.)
  let localSyncWarning: string | undefined;
  if (onTargetBranch) {
    const fetchRes = await runGit(
      ["fetch", "--no-tags", "origin", branch],
      ctx.cwd,
    );
    const syncRes =
      fetchRes.exitCode === 0
        ? await runGit(["merge", "--ff-only", outcome.sha], ctx.cwd)
        : fetchRes;
    if (syncRes.exitCode !== 0) {
      localSyncWarning =
        `the merge is on the remote, but syncing the local checkout failed ` +
        `(${syncRes.stderr.trim()}). Run \`git fetch origin ${branch} && ` +
        `git merge --ff-only origin/${branch}\` before further local work.`;
    }
  }

  return {
    branch,
    base,
    merged: true,
    commit: { sha: outcome.sha, url: outcome.url },
    localSyncWarning,
  };
}
