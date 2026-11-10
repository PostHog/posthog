import * as path from "node:path";
import { isGitlabRun } from "@posthog/git/gitlab";
import type { z } from "zod";
import { isCloudRun } from "../cloud-run";
import { resolveGithubToken } from "../github-token";
import { defineLocalTool, type LocalTool } from "../registry";
import type {
  SignedCommitToolCtx,
  SignedCommitToolResult,
} from "../signed-commit-shared";

/**
 * Factory for the cloud-only GitHub tools (git_signed_commit / git_signed_rewrite /
 * gh_stack), which GitLab runs do not get. Resolves the token lazily (live /tmp/agent-env first, so a mid-session
 * credential refresh takes effect) and the optional `cwd` arg against the session cwd,
 * then delegates to the tool's `run`. Kept past ToolSearch via alwaysLoad by default.
 */
export function defineSignedGitTool<S extends z.ZodRawShape, R>(opts: {
  name: string;
  description: string;
  schema: S;
  alwaysLoad?: boolean;
  run: (ctx: SignedCommitToolCtx, input: R) => Promise<SignedCommitToolResult>;
}): LocalTool {
  return defineLocalTool({
    name: opts.name,
    description: opts.description,
    schema: opts.schema,
    alwaysLoad: opts.alwaysLoad ?? true,
    // GitLab runs push with plain git and open MRs with gitlab_merge_request.
    isEnabled: (_ctx, meta) => isCloudRun(meta) && !isGitlabRun(),
    handler: (ctx, args) => {
      const token = resolveGithubToken() ?? ctx.token;
      if (!token) {
        return Promise.resolve({
          content: [
            {
              type: "text" as const,
              text: `${opts.name} failed: no GitHub token in env (GH_TOKEN/GITHUB_TOKEN)`,
            },
          ],
          isError: true as const,
        });
      }
      const { cwd: argCwd, ...input } = args as { cwd?: string } & Record<
        string,
        unknown
      >;
      const taskRepositoryCwd = path.resolve(ctx.cwd);
      const cwd = argCwd
        ? path.resolve(taskRepositoryCwd, argCwd)
        : taskRepositoryCwd;
      return opts.run(
        {
          cwd,
          taskRepositoryCwd,
          token,
          taskId: ctx.taskId,
          taskRunId: ctx.taskRunId,
          baseBranch: ctx.baseBranch,
        },
        input as R,
      );
    },
  });
}
