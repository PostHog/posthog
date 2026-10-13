import { describe, expect, it, vi } from "vitest";
import { checkoutExistingPullRequest } from "./pr-checkout";

const PR_URL = "https://github.com/PostHog/code/pull/1";
const PR_BRANCH = "posthog-code/fix-checkout";
const PR_HEAD_OID = "abc1234567890abcdef1234567890abcdef12345";
// A SHA that differs from the PR head, used to force the "needs checkout" path.
const OTHER_OID = "0".repeat(40);

type RunCommand = (
  executable: string,
  args: string[],
  cwd: string,
  signal: AbortSignal,
) => Promise<{ stdout: string }>;

/**
 * Builds a runCommand mock that answers the four git/gh calls the checkout
 * makes: `git branch --show-current`, `git rev-parse HEAD`, `gh pr view
 * ... --json headRefName,headRefOid`, and `git remote get-url origin`. Records
 * every call so assertions can pin exact args (including the prUrl and cwd)
 * rather than just call counts.
 */
function buildRunCommand({
  currentBranch = PR_BRANCH,
  currentHead = PR_HEAD_OID,
  prBranch = PR_BRANCH,
  prHeadOid = PR_HEAD_OID,
  originUrl = "https://github.com/PostHog/code.git",
  checkoutError,
}: {
  currentBranch?: string;
  currentHead?: string;
  prBranch?: string;
  prHeadOid?: string;
  originUrl?: string;
  checkoutError?: Error;
} = {}): { runCommand: RunCommand; calls: ReturnType<typeof vi.fn> } {
  const calls = vi.fn();
  const runCommand: RunCommand = async (executable, args, cwd, _signal) => {
    calls(executable, args, cwd);
    if (executable === "git" && args[0] === "branch") {
      return { stdout: `${currentBranch}\n` };
    }
    if (executable === "git" && args[0] === "rev-parse") {
      return { stdout: `${currentHead}\n` };
    }
    if (executable === "git" && args[0] === "remote") {
      return { stdout: `${originUrl}\n` };
    }
    if (executable === "gh" && args[1] === "view") {
      return { stdout: `${prBranch}\n${prHeadOid}\n` };
    }
    if (executable === "gh" && args[1] === "checkout") {
      if (checkoutError) {
        throw checkoutError;
      }
      return { stdout: "" };
    }
    return { stdout: "" };
  };
  return { runCommand, calls };
}

const ghCheckoutCall = (calls: ReturnType<typeof vi.fn>) =>
  calls.mock.calls.find(
    ([executable, args]: string[]) =>
      executable === "gh" && args[0] === "pr" && args[1] === "checkout",
  );

describe("checkoutExistingPullRequest", () => {
  it.each([
    {
      name: "skips checkout when attached to the PR branch at its head commit",
      currentBranch: PR_BRANCH,
      currentHead: PR_HEAD_OID,
      expectedStatus: "already_active",
      expectedCheckoutCalls: 0,
    },
    {
      name: "checks out when HEAD is on the PR branch but behind its head",
      currentBranch: PR_BRANCH,
      currentHead: OTHER_OID,
      expectedStatus: "checked_out",
      expectedCheckoutCalls: 1,
    },
    {
      name: "checks out when on another branch entirely",
      currentBranch: "main",
      currentHead: OTHER_OID,
      expectedStatus: "checked_out",
      expectedCheckoutCalls: 1,
    },
  ])(
    "$name",
    async ({
      currentBranch,
      currentHead,
      expectedStatus,
      expectedCheckoutCalls,
    }) => {
      const { runCommand, calls } = buildRunCommand({
        currentBranch,
        currentHead,
      });
      const result = await checkoutExistingPullRequest({
        repositoryPath: "/tmp/repo",
        prUrl: PR_URL,
        runCommand,
      });

      expect(result.status).toBe(expectedStatus);
      const checkoutCalls = calls.mock.calls.filter(
        ([executable, args]: string[]) =>
          executable === "gh" && args[0] === "pr" && args[1] === "checkout",
      );
      expect(checkoutCalls).toHaveLength(expectedCheckoutCalls);

      // Every git/gh call runs in the repository path — a regression that
      // dropped (or changed) the cwd would not otherwise be caught, since the
      // mock ignores it for dispatch.
      for (const callCwd of calls.mock.calls.map(
        ([, , cwd]: string[]) => cwd,
      )) {
        expect(callCwd).toBe("/tmp/repo");
      }
    },
  );

  it("passes the prUrl through to `gh pr checkout` (not just the call count)", async () => {
    const { runCommand, calls } = buildRunCommand({
      currentBranch: "main",
      currentHead: OTHER_OID,
    });
    await checkoutExistingPullRequest({
      repositoryPath: "/tmp/repo",
      prUrl: PR_URL,
      runCommand,
    });

    expect(ghCheckoutCall(calls)).toBeTruthy();
    // Pins the full args so a future refactor that drops the URL (or passes
    // the wrong variable) fails instead of silently calling `gh pr checkout`
    // with no argument.
    expect(ghCheckoutCall(calls)?.[1]).toEqual(["pr", "checkout", PR_URL]);
  });

  it("checks out when the local branch shares the PR head's name but points at a different commit", async () => {
    // Fork-PR edge case: a local branch named like the fork's head branch but
    // tracking a different remote (different commit). Comparing only branch
    // names would wrongly short-circuit as already_active. The SHA comparison
    // must catch the mismatch and check out.
    const { runCommand, calls } = buildRunCommand({
      currentBranch: PR_BRANCH,
      currentHead: "deadbeef".repeat(5),
    });
    const result = await checkoutExistingPullRequest({
      repositoryPath: "/tmp/repo",
      prUrl: PR_URL,
      runCommand,
    });

    expect(result.status).toBe("checked_out");
    expect(ghCheckoutCall(calls)).toBeTruthy();
  });

  it("checks out when HEAD is detached at the PR head commit (does not skip)", async () => {
    // Detached HEAD at the PR head commit must NOT short-circuit as
    // already_active: new commits would not attach to the PR branch. The
    // branch-name check (empty on detached HEAD) forces a checkout.
    const { runCommand, calls } = buildRunCommand({
      currentBranch: "",
      currentHead: PR_HEAD_OID,
    });
    const result = await checkoutExistingPullRequest({
      repositoryPath: "/tmp/repo",
      prUrl: PR_URL,
      runCommand,
    });

    expect(result.status).toBe("checked_out");
    expect(ghCheckoutCall(calls)).toBeTruthy();
  });

  it("fails when the PR belongs to a different repository than the workspace origin", async () => {
    // `gh pr checkout <url>` treats a full URL as a repository override, so a
    // foreign PR URL could pull an attacker-controlled branch in. The PR's
    // owner/repo must match the workspace's origin.
    const { runCommand, calls } = buildRunCommand({
      originUrl: "https://github.com/PostHog/posthog.git",
    });
    const result = await checkoutExistingPullRequest({
      repositoryPath: "/tmp/repo",
      prUrl: PR_URL,
      runCommand,
    });

    expect(result.status).toBe("failed");
    expect(result).toMatchObject({
      error: expect.stringContaining("not in the workspace repository"),
    });
    expect(ghCheckoutCall(calls)).toBeUndefined();
  });

  it("returns failed when the pull request head branch is empty", async () => {
    const { runCommand } = buildRunCommand({
      prBranch: "",
      prHeadOid: "",
    });
    const result = await checkoutExistingPullRequest({
      repositoryPath: "/tmp/repo",
      prUrl: PR_URL,
      runCommand,
    });

    expect(result).toEqual({
      status: "failed",
      error: "Pull request head branch is empty",
    });
  });

  it("checks out when gh pr view omits the head OID (falls back from SHA match)", async () => {
    // If headRefOid is unavailable, the SHA guard is skipped so checkout
    // proceeds rather than assuming already_active.
    const { runCommand, calls } = buildRunCommand({
      currentBranch: "main",
      currentHead: OTHER_OID,
      prHeadOid: "",
    });
    const result = await checkoutExistingPullRequest({
      repositoryPath: "/tmp/repo",
      prUrl: PR_URL,
      runCommand,
    });

    expect(result.status).toBe("checked_out");
    expect(ghCheckoutCall(calls)).toBeTruthy();
  });

  it("returns a failure when gh pr view succeeds but gh pr checkout fails", async () => {
    const { runCommand } = buildRunCommand({
      currentBranch: "main",
      currentHead: OTHER_OID,
      checkoutError: new Error("branch not found remotely"),
    });
    const result = await checkoutExistingPullRequest({
      repositoryPath: "/tmp/repo",
      prUrl: PR_URL,
      runCommand,
    });

    expect(result).toEqual({
      status: "failed",
      error: "branch not found remotely",
    });
  });

  it("restores the original branch and HEAD after an interrupted checkout", async () => {
    // A deadline-killed `gh pr checkout` can leave the working tree partially
    // switched. The failure path must roll back to the pre-checkout state so
    // the agent's fallback checkout starts clean.
    const { runCommand, calls } = buildRunCommand({
      currentBranch: "main",
      currentHead: OTHER_OID,
      checkoutError: new Error("signal: aborted"),
    });
    const result = await checkoutExistingPullRequest({
      repositoryPath: "/tmp/repo",
      prUrl: PR_URL,
      runCommand,
    });

    expect(result.status).toBe("failed");
    const gitArgs = (
      calls.mock.calls as [string, string[], string, AbortSignal][]
    )
      .filter(([executable]) => executable === "git")
      .map(([, args]) => args.join(" "));
    expect(gitArgs).toContain("merge --abort");
    expect(gitArgs).toContain("checkout --force main");
    expect(gitArgs).toContain(`reset --hard ${OTHER_OID}`);
  });

  it("returns a failure so startup can fall back to agent checkout", async () => {
    const result = await checkoutExistingPullRequest({
      repositoryPath: "/tmp/repo",
      prUrl: PR_URL,
      runCommand: vi.fn().mockRejectedValue(new Error("gh unavailable")),
    });

    expect(result).toEqual({ status: "failed", error: "gh unavailable" });
  });

  it("rejects a non-PR URL without invoking git or gh", async () => {
    const runCommand = vi.fn();
    const result = await checkoutExistingPullRequest({
      repositoryPath: "/tmp/repo",
      prUrl: "https://github.com/PostHog/code/blob/main/README.md",
      runCommand,
    });

    expect(result.status).toBe("failed");
    expect(runCommand).not.toHaveBeenCalled();
  });
});
