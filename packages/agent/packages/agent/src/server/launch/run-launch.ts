import { getProjectWebUrl } from "@posthog/agent-contracts/rich-output-prompt";
import type { PermissionMode } from "../../execution-mode";
import type { ProductLaunchConfiguration, TaskSource } from "../../sdk/product";
import type { Task, TaskRun, TaskRunState } from "../../types";
import type { JwtPayload } from "../jwt";
import { claudeCodeConfigSchema } from "../schemas";
import type { AgentServerConfig, ClaudeCodeConfig } from "../types";
import {
  parseServerRunPolicy,
  RESTRICTIVE_RUN_POLICY,
  type RunPolicy,
} from "./run-policy";

export interface RunLaunchSources {
  readonly payload: Pick<JwtPayload, "task_id" | "run_id" | "user_id">;
  readonly task: Task | null;
  readonly taskRun: TaskRun | null;
  readonly config: Pick<AgentServerConfig, "apiUrl" | "projectId">;
  readonly env: Readonly<Record<string, string | undefined>>;
}

export type RunPolicySource =
  | "server"
  | "missing_server"
  | "invalid_server"
  | "stale_server";

export interface RunLaunch {
  readonly userId: number | null;
  readonly title: string | null;
  readonly originProduct: string | null;
  readonly originKey: string | null;
  readonly interactionOrigin: string | undefined;
  readonly internal: boolean;
  readonly signalReportId: string | null;
  readonly repositories: string[];
  readonly jsonSchema: Record<string, unknown> | null;
  readonly aiStage: string | null;
  readonly aiAgentName: string | null;
  readonly sandboxEnvironmentId: string | null;
  readonly snapshotKind: string | null;
  readonly prewarmed: boolean | null;
  readonly sharedPromptCache: boolean;
  readonly codexMaxSubagents: number | null;
  readonly codexAppsDisabled: boolean;
  readonly initialPermissionMode: PermissionMode | null;
  readonly pendingUserArtifactIds: string[];
  readonly policy: RunPolicy;
  readonly policySource: RunPolicySource;
  readonly disableRepoHooks: boolean;
  readonly disableSkills: boolean;
  readonly systemPrompt: ClaudeCodeConfig["systemPrompt"];
  readonly systemPromptValid: boolean;
  readonly tokenUsage: unknown;
  readonly runState: TaskRunState | null;
}

export function readRunLaunch(sources: RunLaunchSources): RunLaunch {
  const { task, taskRun } = sources;
  const runState = taskRun?.state ?? null;
  const systemPrompt = claudeCodeConfigSchema.shape.systemPrompt.safeParse(
    runState?.systemPrompt,
  );
  const { policy, source: policySource } = readRunPolicy(sources);

  return {
    userId: sources.payload.user_id || task?.created_by?.id || null,
    title: task?.title ?? null,
    originProduct: task?.origin_product ?? null,
    originKey: task?.origin_key ?? null,
    interactionOrigin: readInteractionOrigin(sources.env),
    internal: task?.internal === true,
    signalReportId: task?.signal_report ?? null,
    repositories: readRepositories(task),
    jsonSchema: task?.json_schema ?? null,
    aiStage: runState?.ai_stage ?? null,
    aiAgentName: runState?.ai_agent_name ?? null,
    sandboxEnvironmentId: runState?.sandbox_environment_id ?? null,
    snapshotKind: taskRun ? (runState?.snapshot_kind ?? "absent") : null,
    prewarmed: taskRun ? runState?.prewarmed === true : null,
    sharedPromptCache: runState?.codex_shared_prompt_cache === true,
    codexMaxSubagents: runState?.codex_max_subagents ?? null,
    codexAppsDisabled: runState?.codex_apps_disabled === true,
    initialPermissionMode: runState?.initial_permission_mode ?? null,
    pendingUserArtifactIds: runState?.pending_user_artifact_ids ?? [],
    policy,
    policySource,
    disableRepoHooks: runState?.disable_repo_hooks === true,
    disableSkills: runState?.disable_skills === true,
    systemPrompt: systemPrompt.success ? systemPrompt.data : undefined,
    systemPromptValid: systemPrompt.success,
    tokenUsage: runState?.token_usage,
    runState,
  };
}

/** Run-specific `-c` overrides for the codex app-server, or undefined when the run keeps the defaults. */
export function codexConfigOverrides(
  launch: Pick<RunLaunch, "codexMaxSubagents" | "codexAppsDisabled">,
): Record<string, number | boolean> | undefined {
  const overrides: Record<string, number | boolean> = {};
  // Codex runs at most 3 sub-agents per session at once by default; the main agent does
  // not count. A run that starts more sub-agents at once sets its own limit.
  if (launch.codexMaxSubagents) {
    overrides["agents.max_concurrent_threads_per_session"] =
      launch.codexMaxSubagents;
  }
  // The apps connected to the ChatGPT plan that pays for the run. Slack turns them off when
  // the plan owner has not allowed them, because people who join the thread use the same run.
  if (launch.codexAppsDisabled) {
    overrides["features.apps"] = false;
  }
  return Object.keys(overrides).length ? overrides : undefined;
}

export function readProductLaunch(
  sources: RunLaunchSources,
): ProductLaunchConfiguration {
  return {
    taskId: sources.payload.task_id,
    runId: sources.payload.run_id,
    interactionOrigin: readInteractionOrigin(sources.env),
    clientProvenance: readClientProvenance(sources),
    launchOptions: structuredClone(sources.taskRun?.state ?? {}),
    source: readTaskSource(sources),
  };
}

function readInteractionOrigin(
  env: RunLaunchSources["env"],
): string | undefined {
  return (
    env.POSTHOG_CODE_INTERACTION_ORIGIN ??
    env.CODE_INTERACTION_ORIGIN ??
    env.TWIG_INTERACTION_ORIGIN
  );
}

function readRunPolicy({ payload, env }: RunLaunchSources): {
  policy: RunPolicy;
  source: RunPolicySource;
} {
  const raw = env.POSTHOG_TASK_RUN_POLICY;
  if (!raw) {
    return { policy: RESTRICTIVE_RUN_POLICY, source: "missing_server" };
  }
  const server = parseServerRunPolicy(raw);
  if (!server) {
    return { policy: RESTRICTIVE_RUN_POLICY, source: "invalid_server" };
  }
  if (server.runId !== payload.run_id) {
    return { policy: RESTRICTIVE_RUN_POLICY, source: "stale_server" };
  }
  return { policy: server.policy, source: "server" };
}

function readClientProvenance(sources: RunLaunchSources): string | undefined {
  return (
    sources.task?.client_provenance ||
    readRunPolicy(sources).policy.defaultClientProvenance
  );
}

function readRepositories(task: Task | null): string[] {
  if (task?.repositories?.length) {
    return task.repositories;
  }
  return task?.repository ? [task.repository] : [];
}

// GitHub drops custom URL schemes from links, so Desktop threads use the /code/... web bridge.
function readTaskSource(sources: RunLaunchSources): TaskSource | undefined {
  const { task } = sources;
  if (!task) {
    return undefined;
  }
  const { apiUrl, projectId } = sources.config;
  const projectWebUrl = getProjectWebUrl(apiUrl, projectId);
  if (task.signal_report) {
    return {
      label: "inbox report",
      url: `${projectWebUrl}/inbox/${task.signal_report}`,
    };
  }
  if (!readRunPolicy(sources).policy.threadLink) {
    return undefined;
  }

  const taskId = encodeURIComponent(sources.payload.task_id);
  const clientProvenance = readClientProvenance(sources);
  if (
    clientProvenance === "posthog_web" ||
    clientProvenance === "posthog_mobile"
  ) {
    return {
      label: "PostHog AI chat",
      url: `${projectWebUrl}/ai?task=${taskId}`,
    };
  }
  if (clientProvenance !== "posthog_desktop") {
    return undefined;
  }
  const appUrl = apiUrl.replace(/\/+$/, "");
  const path = task.channel
    ? `code/channel/${encodeURIComponent(task.channel)}/tasks/${taskId}`
    : `code/task/${taskId}`;
  return { label: "PostHog Desktop task", url: `${appUrl}/${path}` };
}
