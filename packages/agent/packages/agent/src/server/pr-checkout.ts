import { execFile } from "node:child_process";
import { promisify } from "node:util";
import { parseGithubUrl } from "@posthog/git/utils";

const execFileAsync = promisify(execFile);

/**
 * Overall budget for the pre-session PR checkout. This is a best-effort
 * optimization: the agent still falls back to its own `gh pr checkout` via the
 * system-prompt instruction when this pre-checkout fails or times out, so the
 * deadline only bounds how long session start waits for it — it does not gate
 * correctness. Per-command child timeouts (below) are larger so a single slow
 * `gh` call is not cut short prematurely, but the total wall-clock spent here
 * is capped so a hung `gh` (auth refresh, stalled fetch) can't stall startup.
 */
const PRE_CHECKOUT_DEADLINE_MS = 60_000;

/** Per-child-process timeout; larger than the overall deadline on purpose. */
const PER_COMMAND_TIMEOUT_MS = 120_000;
const PER_COMMAND_MAX_BUFFER = 10 * 1024 * 1024;

type CommandResult = { stdout: string };
type RunCommand = (
  executable: string,
  args: string[],
  cwd: string,
  signal: AbortSignal,
) => Promise<CommandResult>;

export type ExistingPrCheckoutResult =
  | { status: "already_active"; branch: string }
  | { status: "checked_out"; branch: string }
  | { status: "failed"; error: string };

async function defaultRunCommand(
  executable: string,
  args: string[],
  cwd: string,
  signal: AbortSignal,
): Promise<CommandResult> {
  const { stdout } = await execFileAsync(executable, args, {
    cwd,
    encoding: "utf8",
    timeout: PER_COMMAND_TIMEOUT_MS,
    maxBuffer: PER_COMMAND_MAX_BUFFER,
    // Killing the child on abort guarantees no in-flight checkout keeps
    // mutating the working tree once we've stopped waiting for it.
    signal,
  });
  return { stdout };
}

/**
 * The pull request the workspace should check out, parsed from prUrl. prUrl
 * originates from the agent's own prior `task_run.output.pr_url`, which the
 * codebase documents as user-writable, so we never hand an arbitrary value
 * straight to `gh`. A non-PR value yields null and the agent's lazy checkout
 * takes over.
 */
function parsePrUrl(prUrl: string): {
  owner: string;
  repo: string;
  number: number;
} | null {
  const parsed = parseGithubUrl(prUrl);
  if (parsed?.kind !== "pr") {
    return null;
  }
  return { owner: parsed.owner, repo: parsed.repo, number: parsed.number };
}

export async function checkoutExistingPullRequest({
  repositoryPath,
  prUrl,
  runCommand = defaultRunCommand,
  deadlineMs = PRE_CHECKOUT_DEADLINE_MS,
}: {
  repositoryPath: string;
  prUrl: string;
  runCommand?: RunCommand;
  deadlineMs?: number;
}): Promise<ExistingPrCheckoutResult> {
  const pr = parsePrUrl(prUrl);
  if (!pr) {
    return {
      status: "failed",
      error: `Not a recognized pull request URL: ${prUrl}`,
    };
  }

  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), deadlineMs);

  const withAbort = (
    executable: string,
    args: string[],
    cwd: string,
  ): Promise<CommandResult> =>
    runCommand(executable, args, cwd, controller.signal);

  try {
    const [currentBranchResult, currentHeadResult, prInfoResult, originResult] =
      await Promise.all([
        withAbort("git", ["branch", "--show-current"], repositoryPath),
        withAbort("git", ["rev-parse", "HEAD"], repositoryPath),
        withAbort(
          "gh",
          [
            "pr",
            "view",
            prUrl,
            "--json",
            "headRefName,headRefOid",
            "--jq",
            '.headRefName + "\\n" + .headRefOid',
          ],
          repositoryPath,
        ),
        withAbort("git", ["remote", "get-url", "origin"], repositoryPath),
      ]);
    const [prBranch, prHeadOid] = prInfoResult.stdout
      .split("\n")
      .map((line) => line.trim());
    const currentBranch = currentBranchResult.stdout.trim();
    const currentHead = currentHeadResult.stdout.trim();

    if (!prBranch) {
      return { status: "failed", error: "Pull request head branch is empty" };
    }

    // Reject PRs whose repository does not match the workspace's origin. `gh pr
    // checkout <url>` treats a full URL as a repository override and fetches
    // that PR's ref into the workspace, so a foreign PR URL (the prUrl field is
    // user-writable) could pull an attacker-controlled branch in before the
    // agent starts. Require the PR's owner/repo to match the connected repo.
    const origin = parseGithubUrl(originResult.stdout.trim());
    if (
      !origin ||
      origin.owner.toLowerCase() !== pr.owner.toLowerCase() ||
      origin.repo.toLowerCase() !== pr.repo.toLowerCase()
    ) {
      return {
        status: "failed",
        error: `Pull request ${prUrl} is not in the workspace repository`,
      };
    }

    // Only skip the checkout when HEAD is attached to the PR's branch AND at
    // its head commit. Matching the SHA alone is not enough: a detached HEAD
    // at the same commit would skip checkout, and new commits would then not
    // attach to the PR branch. Matching the branch name alone is not enough
    // either (a fork PR can share a name with a different-local-remote branch).
    if (prHeadOid && currentBranch === prBranch && currentHead === prHeadOid) {
      return { status: "already_active", branch: prBranch };
    }

    // originalHead/originalBranch capture the state before checkout so an
    // interrupted `gh pr checkout` (e.g. the deadline aborting it mid-switch)
    // can be rolled back instead of leaving a partially-switched working tree
    // for the agent's fallback checkout to trip over.
    const originalHead = currentHead;
    const originalBranch = currentBranch;
    try {
      await withAbort("gh", ["pr", "checkout", prUrl], repositoryPath);
    } catch (error) {
      await restoreRepoState(
        runCommand,
        repositoryPath,
        originalBranch,
        originalHead,
      );
      return {
        status: "failed",
        error: error instanceof Error ? error.message : String(error),
      };
    }
    return { status: "checked_out", branch: prBranch };
  } catch (error) {
    return {
      status: "failed",
      error: error instanceof Error ? error.message : String(error),
    };
  } finally {
    clearTimeout(timeout);
    // Ensure no child survives the deadline if we exit early (e.g. the second
    // command failed before the first timed out).
    controller.abort();
  }
}

/**
 * Best-effort restore of the working tree after an interrupted `gh pr
 * checkout`. `gh pr checkout` may run `git fetch` + `git checkout`; if it is
 * killed mid-checkout the index and working tree can be left partially
 * switched. We abort any in-progress merge, return to the original branch (or
 * commit, if HEAD was detached), and hard-reset tracked files to the original
 * commit so the agent's fallback checkout starts from a clean, known state.
 * Runs outside the checkout's deadline (per-command timeout still applies) and
 * swallows its own errors so a failed restore never masks the original failure.
 */
async function restoreRepoState(
  runCommand: RunCommand,
  repositoryPath: string,
  originalBranch: string,
  originalHead: string,
): Promise<void> {
  // Fresh signal — the checkout's controller has already aborted.
  const signal = new AbortController().signal;
  const restore = (args: string[]): Promise<CommandResult> =>
    runCommand("git", args, repositoryPath, signal);
  try {
    // Clear any merge state `gh pr checkout` may have left behind.
    await restore(["merge", "--abort"]).catch(() => {});
    // Detached HEAD pre-checkout: return to the original commit. Otherwise
    // return to the original branch (re-attaching HEAD to it).
    await restore(
      originalBranch
        ? ["checkout", "--force", originalBranch]
        : ["checkout", "--force", originalHead],
    ).catch(() => {});
    // Discard partial index/working-tree changes from the interrupted
    // checkout, restoring tracked files to the original commit. Untracked
    // files (e.g. agent skill bundles under .posthog/) are left alone.
    await restore(["reset", "--hard", originalHead]).catch(() => {});
  } catch {
    // Best-effort: a restore failure must not mask the original checkout
    // failure. The fallback `gh pr checkout` will surface any lingering state.
  }
}
