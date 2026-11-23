import * as path from "node:path";
import { execGit } from "@posthog/git/git-exec";
import {
  createGitlabDraftMergeRequest,
  findGitlabMergeRequestBySourceBranch,
  type GitlabClient,
  type GitlabMergeRequest,
  getGitlabDefaultBranch,
  getGitlabMergeRequest,
  isGitlabRun,
  parseGitlabMergeRequestUrl,
  parseGitlabRemoteProject,
  resolveGitlabClient,
} from "@posthog/git/gitlab";
import { z } from "zod";
import { isCloudRun } from "../cloud-run";
import {
  defineLocalTool,
  type LocalToolResult,
  qualifiedLocalToolName,
} from "../registry";
import { reportTaskRunBranch } from "../signed-commit-artefacts";

export const GITLAB_MERGE_REQUEST_TOOL_NAME = "gitlab_merge_request";
export const GITLAB_MERGE_REQUEST_QUALIFIED_TOOL_NAME = qualifiedLocalToolName(
  GITLAB_MERGE_REQUEST_TOOL_NAME,
);

const DESCRIPTION =
  "Open or read a GitLab merge request (MR) in the project of the origin remote. " +
  'Operation "create" opens a draft MR from a branch you already pushed with ' +
  "`git push -u origin <branch>`. The target branch defaults to the project's default " +
  'branch. Operation "view" reads an MR by URL, iid, or source branch. Use this tool ' +
  "instead of `gh`, which works only with GitHub.";

const schema = {
  operation: z
    .enum(["create", "view"])
    .describe('"create" opens a draft MR. "view" reads an existing MR.'),
  source_branch: z
    .string()
    .min(1)
    .optional()
    .describe(
      'Branch with your commits. For "create" it defaults to the current branch. ' +
        'For "view" it finds the newest MR from this branch.',
    ),
  target_branch: z
    .string()
    .min(1)
    .optional()
    .describe(
      "Branch to merge into. Defaults to the project's default branch.",
    ),
  title: z
    .string()
    .min(1)
    .optional()
    .describe(
      'MR title, required for "create". The tool adds the `Draft: ` prefix.',
    ),
  description: z
    .string()
    .optional()
    .describe('MR description in Markdown, for "create".'),
  merge_request: z
    .string()
    .min(1)
    .optional()
    .describe('For "view": the MR URL or its iid (the number after `!`).'),
  cwd: z
    .string()
    .optional()
    .describe(
      "Path to the git checkout whose origin remote names the project; defaults to the " +
        "session's working directory. Relative paths resolve against the session cwd.",
    ),
};

export interface GitlabMergeRequestInput {
  operation: "create" | "view";
  source_branch?: string;
  target_branch?: string;
  title?: string;
  description?: string;
  merge_request?: string;
}

function ok(text: string): LocalToolResult {
  return { content: [{ type: "text", text }] };
}

function fail(text: string): LocalToolResult {
  return { content: [{ type: "text", text }], isError: true };
}

function formatMergeRequest(mr: GitlabMergeRequest): string {
  return JSON.stringify(
    {
      iid: mr.iid,
      web_url: mr.web_url,
      title: mr.title,
      state: mr.state,
      draft: mr.draft,
      source_branch: mr.source_branch,
      target_branch: mr.target_branch,
    },
    null,
    2,
  );
}

async function gitOutput(cwd: string, args: string[]): Promise<string | null> {
  const res = await execGit(args, { cwd, timeoutMs: 15_000 });
  return res.exitCode === 0 ? res.stdout.trim() : null;
}

export interface GitlabMergeRequestDeps {
  client: GitlabClient;
  projectPath: string;
  currentBranch: () => Promise<string | null>;
  reportBranch: (branch: string) => Promise<void>;
}

export async function runGitlabMergeRequest(
  deps: GitlabMergeRequestDeps,
  input: GitlabMergeRequestInput,
): Promise<LocalToolResult> {
  const { client, projectPath } = deps;
  try {
    if (input.operation === "create") {
      if (!input.title?.trim()) {
        return fail(
          `${GITLAB_MERGE_REQUEST_TOOL_NAME} "create" needs \`title\`.`,
        );
      }
      const sourceBranch = input.source_branch ?? (await deps.currentBranch());
      if (!sourceBranch) {
        return fail(
          "No source branch: pass `source_branch`, or check out the branch you pushed.",
        );
      }
      const targetBranch =
        input.target_branch ??
        (await getGitlabDefaultBranch(client, projectPath));
      if (sourceBranch === targetBranch) {
        return fail(
          `The source branch is the target branch (${targetBranch}). Create a new branch, ` +
            "commit, and push it first.",
        );
      }
      const mr = await createGitlabDraftMergeRequest(client, projectPath, {
        sourceBranch,
        targetBranch,
        title: input.title,
        description: input.description,
      });
      await deps.reportBranch(mr.source_branch);
      return ok(`Created a draft merge request.\n${formatMergeRequest(mr)}`);
    }

    if (input.merge_request) {
      const raw = input.merge_request.trim().replace(/^!/, "");
      let iid: number | null = null;
      if (/^[1-9]\d*$/.test(raw)) {
        iid = Number(raw);
      } else {
        const ref = parseGitlabMergeRequestUrl(raw, client.host);
        if (!ref) {
          return fail(`Not a GitLab merge request URL or iid: ${raw}`);
        }
        if (ref.projectPath.toLowerCase() !== projectPath.toLowerCase()) {
          return fail(
            `Merge request ${raw} is not in the workspace project ${projectPath}.`,
          );
        }
        iid = ref.iid;
      }
      return ok(
        formatMergeRequest(
          await getGitlabMergeRequest(client, projectPath, iid),
        ),
      );
    }

    const sourceBranch = input.source_branch ?? (await deps.currentBranch());
    if (!sourceBranch) {
      return fail(
        `${GITLAB_MERGE_REQUEST_TOOL_NAME} "view" needs \`merge_request\` or \`source_branch\`.`,
      );
    }
    const mr = await findGitlabMergeRequestBySourceBranch(
      client,
      projectPath,
      sourceBranch,
    );
    return mr
      ? ok(formatMergeRequest(mr))
      : ok(`No merge request has source branch ${sourceBranch}.`);
  } catch (err) {
    return fail(err instanceof Error ? err.message : String(err));
  }
}

export const gitlabMergeRequestTool = defineLocalTool({
  name: GITLAB_MERGE_REQUEST_TOOL_NAME,
  description: DESCRIPTION,
  schema,
  alwaysLoad: true,
  isEnabled: (_ctx, meta) => isCloudRun(meta) && isGitlabRun(),
  handler: async (ctx, args) => {
    const client = resolveGitlabClient();
    if (!client) {
      return fail(
        `${GITLAB_MERGE_REQUEST_TOOL_NAME} failed: no GitLab token in env (GITLAB_TOKEN)`,
      );
    }
    const { cwd: argCwd, ...input } = args;
    const taskRepositoryCwd = path.resolve(ctx.cwd);
    const cwd = argCwd
      ? path.resolve(taskRepositoryCwd, argCwd)
      : taskRepositoryCwd;
    // The origin URL holds the token, so never put it in a message.
    const projectPath = parseGitlabRemoteProject(
      await gitOutput(cwd, ["remote", "get-url", "origin"]),
      client.host,
    );
    if (!projectPath) {
      return fail(
        `${GITLAB_MERGE_REQUEST_TOOL_NAME} failed: the origin remote in ${cwd} is not a ${client.host} project`,
      );
    }
    return runGitlabMergeRequest(
      {
        client,
        projectPath,
        currentBranch: () => gitOutput(cwd, ["branch", "--show-current"]),
        reportBranch: (branch) =>
          reportTaskRunBranch({
            taskId: ctx.taskId,
            taskRunId: ctx.taskRunId,
            repository: projectPath,
            updateCheckoutBranch: cwd === taskRepositoryCwd,
            branch,
          }),
      },
      input,
    );
  },
});
