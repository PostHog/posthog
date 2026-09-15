import { execGh } from "@posthog/git/gh";
import { z } from "zod";
import { resolveGithubToken } from "../../../utils/github-token";
import { defineLocalTool, type LocalToolResult } from "../registry";

const GH_TIMEOUT_MS = 30_000;
const GH_MAX_BUFFER = 1024 * 1024 * 8;
const INSTALLATION_PAGE_SIZE = 100;
/** `limit` caps at 200, so three pages cover it with room for later filtering. */
const INSTALLATION_MAX_PAGES = 3;

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

interface Repo {
  nameWithOwner: string;
  description?: string | null;
}

const ghRepoSchema = z.array(
  z.object({
    nameWithOwner: z.string(),
    description: z.string().nullish(),
  }),
);

const installationReposSchema = z.object({
  repositories: z.array(
    z.object({
      full_name: z.string(),
      description: z.string().nullish(),
      archived: z.boolean().nullish(),
    }),
  ),
});

type GhEnv = Record<string, string> | undefined;

async function runGh(args: string[], env: GhEnv): Promise<string> {
  // Bound the subprocess. Without a timeout a stalled gh network call keeps the
  // tool call, and the agent turn awaiting it, pending with no recovery.
  const res = await execGh(args, {
    env,
    timeoutMs: GH_TIMEOUT_MS,
    maxBuffer: GH_MAX_BUFFER,
  });
  if (res.exitCode !== 0) {
    throw new Error(res.error || res.stderr.trim() || "gh failed");
  }
  return res.stdout;
}

/** Repositories owned by the user the token authenticates as. */
async function listOwnedRepos(
  env: GhEnv,
  owner: string | undefined,
  limit: number,
): Promise<Repo[]> {
  const args = ["repo", "list"];
  if (owner) args.push(owner);
  args.push(
    "--no-archived",
    "--json",
    "nameWithOwner,description",
    "--limit",
    String(limit),
  );

  const parsed = ghRepoSchema.safeParse(JSON.parse(await runGh(args, env)));
  if (!parsed.success) {
    throw new Error(
      `unexpected output from 'gh repo list'. ${parsed.error.message}`,
    );
  }
  return parsed.data;
}

/** Repositories the GitHub App installation behind the token can reach. */
async function listInstallationRepos(env: GhEnv): Promise<Repo[]> {
  const repos: Repo[] = [];
  for (let page = 1; page <= INSTALLATION_MAX_PAGES; page++) {
    const stdout = await runGh(
      [
        "api",
        `/installation/repositories?per_page=${INSTALLATION_PAGE_SIZE}&page=${page}`,
      ],
      env,
    );
    const parsed = installationReposSchema.safeParse(JSON.parse(stdout));
    if (!parsed.success) {
      throw new Error(
        `unexpected output from 'gh api /installation/repositories'. ${parsed.error.message}`,
      );
    }
    const batch = parsed.data.repositories;
    for (const repo of batch) {
      // `gh repo list` passes --no-archived; match it so both paths agree.
      if (repo.archived) continue;
      repos.push({
        nameWithOwner: repo.full_name,
        description: repo.description,
      });
    }
    if (batch.length < INSTALLATION_PAGE_SIZE) break;
  }
  return repos;
}

function filterRepos(
  repos: Repo[],
  owner: string | undefined,
  query: string | undefined,
): Repo[] {
  let filtered = repos;
  if (owner) {
    const prefix = `${owner.toLowerCase()}/`;
    filtered = filtered.filter((r) =>
      r.nameWithOwner.toLowerCase().startsWith(prefix),
    );
  }
  if (query) {
    const q = query.toLowerCase();
    filtered = filtered.filter((r) =>
      r.nameWithOwner.toLowerCase().includes(q),
    );
  }
  return filtered;
}

function ghFailure(err: unknown): LocalToolResult {
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

/**
 * Lists candidate GitHub repositories for a repo-less channel session, via the
 * `gh` CLI. The agent cross-references these against the channel CONTEXT.md
 * (which lists the most likely repos) and asks the user if still unsure.
 */
export const listReposTool = defineLocalTool({
  name: "list_repos",
  description:
    "List available GitHub repositories (channel tasks only): your own repos, " +
    "or the repos connected to this project when the sandbox holds a project " +
    "token. Use to discover which repo a coding task belongs to. Prefer repos " +
    "named in the channel CONTEXT.md; if still unsure, ask the user before cloning.",
  schema: listReposSchema,
  alwaysLoad: true,
  isEnabled: (_ctx, meta) => meta?.channelMode === true,
  handler: async (ctx, args): Promise<LocalToolResult> => {
    const { owner, query } = args;
    const limit = args.limit ?? 50;
    const token = resolveGithubToken() ?? ctx.token;

    // An empty token is a managed logout, not "no preference": clear both token
    // vars so gh cannot fall back to the previous actor's frozen process-env
    // token and enumerate their private repos. Only an undefined token (an
    // unmanaged local/desktop sandbox) inherits the process env unchanged.
    // execGh merges these overrides onto process.env, so the rest of the env
    // still passes through.
    const env =
      token === undefined
        ? undefined
        : { GH_TOKEN: token, GITHUB_TOKEN: token };

    let repos: Repo[] = [];
    let ownedError: unknown;
    try {
      repos = await listOwnedRepos(env, owner, limit);
    } catch (err) {
      ownedError = err;
    }

    // `gh repo list` enumerates the repositories of the *user* the token
    // authenticates as. A GitHub App installation token has no user behind it,
    // so a scout or channel sandbox gets an empty list however many repositories
    // the project connected. Fall back to the endpoint such a token can
    // enumerate, which is scoped to exactly what the installation was granted.
    if (repos.length === 0) {
      try {
        repos = await listInstallationRepos(env);
      } catch {
        // A user token always gets 403 here, so its own failure is the useful
        // one to report. An empty-but-successful user listing is not a failure.
        if (ownedError !== undefined) {
          return ghFailure(ownedError);
        }
      }
    }

    const found = filterRepos(repos, owner, query).slice(0, limit);
    if (found.length === 0) {
      return { content: [{ type: "text", text: "No repositories found." }] };
    }
    const lines = found.map((r) =>
      r.description ? `${r.nameWithOwner}: ${r.description}` : r.nameWithOwner,
    );
    return { content: [{ type: "text", text: lines.join("\n") }] };
  },
});
