import * as fs from "node:fs";
import * as path from "node:path";
import { createGitClient } from "@posthog/git/client";
import { getCurrentBranch } from "@posthog/git/queries";
import { CloneSaga } from "@posthog/git/sagas/clone";
import { parseGithubUrl } from "@posthog/git/utils";
import { z } from "zod";
import { resolveGithubToken } from "../../../utils/github-token";
import { defineLocalTool, type LocalToolResult } from "../registry";

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
 * Lazily brings a repo into a repo-less channel session's scratch workspace.
 * Clones into `<cwd>/repos/<repo>` (a subdir of the session cwd, so no session
 * restart / cwd rebind is needed) and reports the path for the agent to cd into.
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

    // Never surface the token to the model/transcript: git may echo the remote
    // URL (with its embedded basic-auth credential) into error output.
    const redact = (text: string): string =>
      token ? text.split(token).join("***") : text;

    // parseGithubUrl accepts owner/repo shorthand and full https/ssh URLs,
    // validates the host, and normalizes away path traversal (a crafted URL
    // can't escape the scratch workspace via the path.join below).
    const parsed = parseGithubUrl(repo);
    if (!parsed) {
      return fail(
        `clone_repo: invalid repo "${repo}". Pass 'owner/repo' or a full https://github.com/... URL.`,
      );
    }
    const slug = `${parsed.owner}/${parsed.repo}`;
    const repoName = parsed.repo;
    const targetPath = path.join(ctx.cwd, "repos", slug);

    const done = async (note?: string): Promise<LocalToolResult> => {
      const checkedOut = (await getCurrentBranch(targetPath)) ?? branch ?? null;
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

    const checkout = async (): Promise<LocalToolResult | null> => {
      if (!branch) return null;
      try {
        await createGitClient(targetPath).checkout(branch);
        return null;
      } catch (err) {
        return fail(
          `Cloned ${slug} to ${targetPath} but failed to check out branch "${branch}": ${redact(
            err instanceof Error ? err.message : String(err),
          )}. The default branch is checked out instead.`,
        );
      }
    };

    // Idempotent: a prior clone (retry, reconnected session, LLM loop) leaves
    // the repo in place. Reuse it instead of letting git abort on a non-empty
    // destination, which the agent would receive as an opaque error.
    if (fs.existsSync(path.join(targetPath, ".git"))) {
      return (
        (await checkout()) ??
        (await done(`${slug} already cloned at ${targetPath}`))
      );
    }

    // GitHub accepts a token as the basic-auth username for https clones; this
    // covers private repos. Public repos clone fine without it.
    const cloneUrl = token
      ? `https://x-access-token:${token}@github.com/${slug}.git`
      : `https://github.com/${slug}.git`;

    try {
      const result = await new CloneSaga().run({
        repoUrl: cloneUrl,
        targetPath,
      });
      if (!result.success) {
        return fail(`clone_repo failed: ${redact(result.error)}`);
      }

      return (await checkout()) ?? (await done());
    } catch (err) {
      return fail(
        `clone_repo failed: ${redact(
          err instanceof Error ? err.message : String(err),
        )}`,
      );
    }
  },
});
