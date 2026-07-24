import { execFile } from "node:child_process";
import { promisify } from "node:util";
import { z } from "zod";
import { resolveGithubToken } from "../../../utils/github-token";
import { defineLocalTool, type LocalToolResult } from "../registry";

const execFileAsync = promisify(execFile);

const listReposSchema = {
  owner: z
    .string()
    .optional()
    .describe("GitHub org or user to list repos for. Omit to list your own."),
  query: z
    .string()
    .optional()
    .describe("Case-insensitive substring to filter repository names by."),
  limit: z
    .number()
    .int()
    .min(1)
    .max(200)
    .optional()
    .describe("Max repos to return (default 50)."),
};

const ghRepoSchema = z.array(
  z.object({
    nameWithOwner: z.string(),
    description: z.string().nullish(),
  }),
);

/**
 * Lists candidate GitHub repositories for a repo-less channel session, via the
 * `gh` CLI. The agent cross-references these against the channel CONTEXT.md
 * (which lists the most likely repos) and asks the user if still unsure.
 */
export const listReposTool = defineLocalTool({
  name: "list_repos",
  description:
    "List available GitHub repositories (channel tasks only). Use to discover " +
    "which repo a coding task belongs to. Prefer repos named in the channel " +
    "CONTEXT.md; if still unsure, ask the user before cloning.",
  schema: listReposSchema,
  alwaysLoad: true,
  isEnabled: (_ctx, meta) => meta?.channelMode === true,
  handler: async (ctx, args): Promise<LocalToolResult> => {
    const { owner, query, limit } = args;
    const token = resolveGithubToken() ?? ctx.token;

    const cmdArgs = ["repo", "list"];
    if (owner) cmdArgs.push(owner);
    cmdArgs.push(
      "--no-archived",
      "--json",
      "nameWithOwner,description",
      "--limit",
      String(limit ?? 50),
    );

    try {
      const { stdout } = await execFileAsync("gh", cmdArgs, {
        env: token ? { ...process.env, GH_TOKEN: token } : process.env,
        maxBuffer: 1024 * 1024 * 8,
      });
      const parsed = ghRepoSchema.safeParse(JSON.parse(stdout));
      if (!parsed.success) {
        return {
          content: [
            {
              type: "text",
              text: `list_repos: unexpected output from gh. ${parsed.error.message}`,
            },
          ],
          isError: true,
        };
      }
      let repos = parsed.data;
      if (query) {
        const q = query.toLowerCase();
        repos = repos.filter((r) => r.nameWithOwner.toLowerCase().includes(q));
      }
      if (repos.length === 0) {
        return {
          content: [{ type: "text", text: "No repositories found." }],
        };
      }
      const lines = repos.map((r) =>
        r.description
          ? `${r.nameWithOwner}: ${r.description}`
          : r.nameWithOwner,
      );
      return { content: [{ type: "text", text: lines.join("\n") }] };
    } catch (err) {
      return {
        content: [
          {
            type: "text",
            text:
              `Couldn't list repositories via gh (${
                err instanceof Error ? err.message : String(err)
              }). Determine the repo from the request and the channel CONTEXT.md, ` +
              `or ask the user which repo to use, then call clone_repo with 'owner/repo'.`,
          },
        ],
        isError: true,
      };
    }
  },
});
