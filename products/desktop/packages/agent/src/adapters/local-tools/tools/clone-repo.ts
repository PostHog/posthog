import * as fs from "node:fs";
import * as fsPromises from "node:fs/promises";
import * as path from "node:path";
import {
  execGit,
  execGitWithRetry,
  type GitExecResult,
} from "@posthog/git/git-exec";
import { parseGithubUrl } from "@posthog/git/utils";
import { z } from "zod";
import { resolveGithubToken } from "../../../utils/github-token";
import { defineLocalTool, type LocalToolResult } from "../registry";

const GIT_TIMEOUT_MS = 10 * 60 * 1000;
const GITHUB_BASE_URL = "https://github.com/";

/**
 * Scoping the auth header to github.com is what keeps the token from being
 * sent to other hosts; an unscoped `http.extraHeader` rides along on every
 * HTTP remote git talks to.
 */
export const GITHUB_AUTH_CONFIG_KEY = `http.${GITHUB_BASE_URL}.extraHeader`;

const cloneRepoSchema = {
  repo: z
    .string()
    .describe(
      "Repository to clone, as 'owner/repo' (preferred) or a full https GitHub URL.",
    ),
  branch: z
    .string()
    .optional()
    .describe(
      "Optional branch to check out. Defaults to the repo's default branch.",
    ),
};

function fail(text: string): LocalToolResult {
  return { content: [{ type: "text", text }], isError: true };
}

/**
 * Carries the token as an `http.extraHeader` in the child's environment, so it
 * never reaches `.git/config` the way a credential embedded in the remote URL
 * would.
 */
function gitEnv(token: string | undefined): Record<string, string> {
  // Repos declaring `filter=lfs` fail outright when git-lfs isn't installed;
  // skipping the smudge filter leaves pointer files instead.
  const env: Record<string, string> = { GIT_LFS_SKIP_SMUDGE: "1" };
  if (!token) return env;
  const basicAuth = Buffer.from(`x-access-token:${token}`).toString("base64");
  return {
    ...env,
    GIT_CONFIG_COUNT: "1",
    GIT_CONFIG_KEY_0: GITHUB_AUTH_CONFIG_KEY,
    GIT_CONFIG_VALUE_0: `AUTHORIZATION: basic ${basicAuth}`,
  };
}

/**
 * Concurrent calls for the same repo (a parallel tool-call batch, a client
 * retry racing a slow clone) would otherwise interleave on one checkout, and
 * the failure-path cleanup could delete a directory the other call is still
 * cloning into.
 */
const inFlight = new Map<string, Promise<LocalToolResult>>();

function withCloneLock(
  targetPath: string,
  task: () => Promise<LocalToolResult>,
): Promise<LocalToolResult> {
  const previous = inFlight.get(targetPath);
  const current = previous ? previous.then(task, task) : task();
  inFlight.set(targetPath, current);
  const cleanup = (): void => {
    if (inFlight.get(targetPath) === current) inFlight.delete(targetPath);
  };
  current.then(cleanup, cleanup);
  return current;
}

/**
 * Lazily brings a repo into a repo-less channel session's scratch workspace.
 * Clones into `<cwd>/repos/<repo>` (a subdir of the session cwd, so no session
 * restart / cwd rebind is needed) and reports the path for the agent to cd into.
 *
 * Goes straight to `git` rather than through the simple-git client and its
 * clone saga: this only ever runs inside agent-server, against a scratch
 * checkout the desktop client never touches, so the client's repo locking and
 * rollback bookkeeping buy nothing (same-session calls are serialized by
 * `withCloneLock`), and the raw subprocess passes `GIT_CONFIG_*` auth through
 * as-is.
 */
export const cloneRepoTool = defineLocalTool({
  name: "clone_repo",
  description:
    "Clone a git repository into your working directory (channel tasks only). " +
    "Use this once you've determined a coding task needs a specific repo. " +
    "Returns the local path to cd into. Prefer repos named in the channel CONTEXT.md.",
  schema: cloneRepoSchema,
  alwaysLoad: true,
  isEnabled: (_ctx, meta) => meta?.channelMode === true,
  handler: async (ctx, args): Promise<LocalToolResult> => {
    const { repo, branch } = args;
    const token = resolveGithubToken() ?? ctx.token;
    const env = gitEnv(token);

    // Never surface the token to the model/transcript: git may echo the remote
    // URL (with its embedded basic-auth credential) into error output.
    const redact = (text: string): string =>
      token ? text.split(token).join("***") : text;

    // parseGithubUrl accepts owner/repo shorthand and full https/ssh URLs,
    // validates the host, and rejects dot segments and unsafe characters in
    // owner and repo, so a crafted URL can't escape the scratch workspace via
    // the path.join below.
    const parsed = parseGithubUrl(repo);
    if (!parsed) {
      return fail(
        `clone_repo: invalid repo "${repo}". Pass 'owner/repo' or a full https://github.com/... URL.`,
      );
    }
    const slug = `${parsed.owner}/${parsed.repo}`;
    const repoName = parsed.repo;
    const targetPath = path.join(ctx.cwd, "repos", slug);
    const cloneUrl = `${GITHUB_BASE_URL}${slug}.git`;

    const git = (gitArgs: string[], cwd?: string): Promise<GitExecResult> =>
      execGit(gitArgs, { cwd, env, timeoutMs: GIT_TIMEOUT_MS });

    // For the network-touching calls (clone, fetch), so a transient blip
    // retries with backoff instead of failing the whole tool call.
    const gitWithRetry = (
      gitArgs: string[],
      cwd?: string,
    ): Promise<GitExecResult> =>
      execGitWithRetry(gitArgs, { cwd, env, timeoutMs: GIT_TIMEOUT_MS });

    const run = async (
      gitArgs: string[],
      cwd?: string,
      exec: typeof git = git,
    ): Promise<string> => {
      const result = await exec(gitArgs, cwd);
      if (result.exitCode !== 0) {
        throw new Error(result.stderr.trim() || result.error || "git failed");
      }
      return result.stdout.trim();
    };

    const done = async (note?: string): Promise<LocalToolResult> => {
      const head = await git(["rev-parse", "--abbrev-ref", "HEAD"], targetPath);
      const headRef = head.exitCode === 0 ? head.stdout.trim() : null;
      const checkedOut =
        headRef && headRef !== "HEAD" ? headRef : (branch ?? null);
      return {
        content: [
          {
            type: "text",
            text: `${note ?? `Cloned ${slug} (${repoName}) to ${targetPath}`}${
              checkedOut ? ` on branch ${checkedOut}` : ""
            }. cd into this path for all git and file work in this repo.`,
          },
        ],
      };
    };

    // The clone is single-branch, so a branch the agent asks for later isn't
    // in the checkout yet — fetch it at depth 1 and register its refspec.
    const checkout = async (): Promise<LocalToolResult | null> => {
      if (!branch) return null;
      const local = await git(["checkout", branch], targetPath);
      if (local.exitCode === 0) return null;
      try {
        const refspec = `+refs/heads/${branch}:refs/remotes/origin/${branch}`;
        await run(
          ["fetch", "--depth", "1", "--no-tags", "origin", refspec],
          targetPath,
          gitWithRetry,
        );
        const configured = await git(
          ["config", "--get-all", "remote.origin.fetch"],
          targetPath,
        );
        if (!configured.stdout.split("\n").includes(refspec)) {
          await run(
            ["config", "--add", "remote.origin.fetch", refspec],
            targetPath,
          );
        }
        await run(
          ["checkout", "-b", branch, "--track", `origin/${branch}`],
          targetPath,
        );
        return null;
      } catch (err) {
        return fail(
          `Cloned ${slug} to ${targetPath} but failed to check out branch "${branch}": ${redact(
            err instanceof Error ? err.message : String(err),
          )}. The previously checked out branch is still active.`,
        );
      }
    };

    const freshClone = async (): Promise<LocalToolResult> => {
      try {
        await fsPromises.mkdir(path.dirname(targetPath), { recursive: true });
        const cloneArgs = [
          "clone",
          "--depth",
          "1",
          "--single-branch",
          "--no-tags",
        ];
        if (branch) {
          cloneArgs.push("--branch", branch);
        }
        await run(
          [...cloneArgs, cloneUrl, targetPath],
          undefined,
          gitWithRetry,
        );
        return done();
      } catch (err) {
        // A partial clone would make the retry above take the "already cloned"
        // path against a broken checkout.
        await fsPromises.rm(targetPath, { recursive: true, force: true });
        return fail(
          `clone_repo failed: ${redact(
            err instanceof Error ? err.message : String(err),
          )}`,
        );
      }
    };

    // A wedged checkout (stale lock, broken config) would otherwise fail every
    // future call for this repo, but one holding local work must not be
    // deleted to recover.
    const discardIfClean = async (): Promise<boolean> => {
      const status = await git(["status", "--porcelain"], targetPath);
      if (status.exitCode !== 0 || status.stdout.trim() !== "") {
        return false;
      }
      await fsPromises.rm(targetPath, { recursive: true, force: true });
      return true;
    };

    return withCloneLock(targetPath, async () => {
      // Idempotent: a prior clone (retry, reconnected session, LLM loop)
      // leaves the repo in place. Reuse it instead of letting git abort on a
      // non-empty destination, which the agent would receive as an opaque
      // error.
      if (fs.existsSync(path.join(targetPath, ".git"))) {
        try {
          // Only this tool writes to `repos/<owner>/<repo>`, so origin should
          // already be `cloneUrl`. Anything else was retargeted after the
          // clone: normalize it before the fetch below, both to keep a
          // credential out of the config and to keep the fetch pointed at the
          // repo we were asked for. Read the stored value rather than
          // `remote get-url`, which resolves `url.<base>.insteadOf` and would
          // mask both.
          const originUrl = await run(
            ["config", "--get", "remote.origin.url"],
            targetPath,
          );
          if (originUrl !== cloneUrl) {
            await run(["remote", "set-url", "origin", cloneUrl], targetPath);
          }
        } catch (err) {
          if (await discardIfClean()) {
            return freshClone();
          }
          return fail(
            `clone_repo couldn't secure the existing origin: ${redact(
              err instanceof Error ? err.message : String(err),
            )}`,
          );
        }
        const checkoutFailure = await checkout();
        if (checkoutFailure) {
          if (await discardIfClean()) {
            return freshClone();
          }
          return checkoutFailure;
        }
        return done(`${slug} already cloned at ${targetPath}`);
      }

      return freshClone();
    });
  },
});
