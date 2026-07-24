import { readFileSync } from "node:fs";
import type { SignedCommitResult } from "@posthog/git/signed-commit";
import { PostHogAPIClient } from "./posthog-api";

const SANDBOX_ENV_FILE = "/tmp/agent-env";

/**
 * Best-effort "commit hook": after a successful signed-commit push, record one `commit`
 * artefact per pushed commit on every signal report the task is associated with, so the
 * report's work log shows exactly what landed. Attribution is deterministic — the artefact
 * endpoint reads the `X-PostHog-Task-Id` header, never the model.
 *
 * Credentials come from the sandbox environment (`POSTHOG_API_URL` /
 * `POSTHOG_PERSONAL_API_KEY` / `POSTHOG_PROJECT_ID`), preferring the live agentsh env file
 * for the key so a mid-session token refresh is picked up — the same pattern as
 * `resolveGithubToken`. Works identically from the Claude in-process server and the Codex
 * stdio child (both inherit the sandbox env). Never throws: a failed artefact post must not
 * fail the commit that already landed.
 */

interface SandboxPosthogApi {
  apiUrl: string;
  apiKey: string;
  projectId: number;
}

function readSandboxEnvFile(envFilePath: string): Record<string, string> {
  try {
    const raw = readFileSync(envFilePath, "utf8");
    const env: Record<string, string> = {};
    for (const entry of raw.split("\0")) {
      const eq = entry.indexOf("=");
      if (eq > 0) {
        env[entry.slice(0, eq)] = entry.slice(eq + 1);
      }
    }
    return env;
  } catch {
    // No env file (local/desktop or test) — fall back to the process env only.
    return {};
  }
}

export function resolveSandboxPosthogApi(
  env: Record<string, string | undefined> = process.env,
  envFilePath: string = SANDBOX_ENV_FILE,
): SandboxPosthogApi | undefined {
  const fileEnv = readSandboxEnvFile(envFilePath);
  const apiUrl = fileEnv.POSTHOG_API_URL ?? env.POSTHOG_API_URL;
  const apiKey =
    fileEnv.POSTHOG_PERSONAL_API_KEY ?? env.POSTHOG_PERSONAL_API_KEY;
  const projectId = Number(
    fileEnv.POSTHOG_PROJECT_ID ?? env.POSTHOG_PROJECT_ID,
  );
  if (!apiUrl || !apiKey || !Number.isFinite(projectId) || projectId <= 0) {
    return undefined;
  }
  return { apiUrl, apiKey, projectId };
}

export function createSandboxPosthogClient(
  env?: Record<string, string | undefined>,
  envFilePath?: string,
): PostHogAPIClient | undefined {
  const api = resolveSandboxPosthogApi(env, envFilePath);
  if (!api) {
    return undefined;
  }
  return new PostHogAPIClient({
    apiUrl: api.apiUrl,
    projectId: api.projectId,
    getApiKey: () => api.apiKey,
  });
}

export async function reportCommitArtefacts(opts: {
  taskId: string | undefined;
  result: SignedCommitResult;
  /** Commit headline — the same for every chunk of a split payload. */
  message: string;
  env?: Record<string, string | undefined>;
  envFilePath?: string;
}): Promise<void> {
  const { taskId, result, message } = opts;
  if (!taskId) {
    return; // Local/desktop run — no task to attribute or associate through.
  }
  try {
    const client = createSandboxPosthogClient(opts.env, opts.envFilePath);
    if (!client) {
      return; // No sandbox PostHog credentials — nothing to report to.
    }
    const reportIds = await client.getSignalReportIdsForTask(taskId);
    for (const reportId of reportIds) {
      for (const commit of result.commits) {
        try {
          await client.createSignalReportArtefact(reportId, taskId, {
            artefact_type: "commit",
            content: {
              repository: result.repository,
              branch: result.branch,
              commit_sha: commit.sha,
              message,
            },
          });
        } catch (err) {
          warn(
            `failed to record commit ${commit.sha} on report ${reportId}: ${err}`,
          );
        }
      }
    }
  } catch (err) {
    warn(`failed to record commit artefacts: ${err}`);
  }
}

export async function reportTaskRunBranch(opts: {
  taskId: string | undefined;
  taskRunId: string | undefined;
  branch: string;
  env?: Record<string, string | undefined>;
  envFilePath?: string;
}): Promise<void> {
  if (!opts.taskId || !opts.taskRunId) {
    return;
  }
  try {
    const client = createSandboxPosthogClient(opts.env, opts.envFilePath);
    if (!client) {
      return;
    }
    await client.updateTaskRun(opts.taskId, opts.taskRunId, {
      branch: opts.branch,
      output: { head_branch: opts.branch },
    });
  } catch (err) {
    warn(`failed to attach branch ${opts.branch} to task run: ${err}`);
  }
}

// stderr directly (not console) — this also runs inside the Codex stdio MCP child,
// where stdout is the protocol channel.
function warn(message: string): void {
  process.stderr.write(`[signed-commit-artefacts] ${message}\n`);
}
