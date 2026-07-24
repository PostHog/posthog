import * as path from "node:path";
import type { z } from "zod";
import { isCloudRun } from "../../../utils/common";
import { resolveGithubToken } from "../../../utils/github-token";
import type {
  SignedCommitToolCtx,
  SignedCommitToolResult,
} from "../../signed-commit-shared";
import { defineLocalTool, type LocalTool } from "../registry";

/**
 * Factory for the cloud-only signed-git tools (git_signed_commit / git_signed_rewrite).
 * Resolves the token lazily (live /tmp/agent-env first, so a mid-session credential
 * refresh takes effect) and the optional `cwd` arg against the session cwd, then
 * delegates to the tool's `run`. Kept past ToolSearch via alwaysLoad.
 */
export function defineSignedGitTool<S extends z.ZodRawShape, R>(opts: {
  name: string;
  description: string;
  schema: S;
  run: (ctx: SignedCommitToolCtx, input: R) => Promise<SignedCommitToolResult>;
}): LocalTool {
  return defineLocalTool({
    name: opts.name,
    description: opts.description,
    schema: opts.schema,
    alwaysLoad: true,
    isEnabled: (_ctx, meta) => isCloudRun(meta),
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
      const cwd = argCwd ? path.resolve(ctx.cwd, argCwd) : ctx.cwd;
      return opts.run(
        {
          cwd,
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
