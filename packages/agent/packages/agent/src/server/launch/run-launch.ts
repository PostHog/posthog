import { getProjectWebUrl } from "@posthog/agent-contracts/rich-output-prompt";
import type { PermissionMode } from "../../execution-mode";
import type { ProductLaunchConfiguration, TaskSource } from "../../sdk/product";
import type { Task, TaskRun, TaskRunState } from "../../types";
import type { JwtPayload } from "../jwt";
import { claudeCodeConfigSchema } from "../schemas";
import type { AgentServerConfig, ClaudeCodeConfig } from "../types";

export interface RunLaunchSources {
  readonly payload: Pick<JwtPayload, "task_id" | "run_id" | "user_id">;
  readonly task: Task | null;
  readonly taskRun: TaskRun | null;
  readonly config: Pick<AgentServerConfig, "apiUrl" | "projectId">;
  readonly env: Readonly<Record<string, string | undefined>>;
}

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
  readonly initialPermissionMode: PermissionMode | null;
  readonly pendingUserArtifactIds: string[];
  readonly endRunWhenDone: boolean;
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
    initialPermissionMode: runState?.initial_permission_mode ?? null,
    pendingUserArtifactIds: runState?.pending_user_artifact_ids ?? [],
    endRunWhenDone: runState?.end_run_when_done === true,
    systemPrompt: systemPrompt.success ? systemPrompt.data : undefined,
    systemPromptValid: systemPrompt.success,
    tokenUsage: runState?.token_usage,
    runState,
  };
}

export function readProductLaunch(
  sources: RunLaunchSources,
): ProductLaunchConfiguration {
  return {
    taskId: sources.payload.task_id,
    runId: sources.payload.run_id,
    originProduct: readInteractionOrigin(sources.env),
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

function readRepositories(task: Task | null): string[] {
  if (task?.repositories?.length) {
    return task.repositories;
  }
  return task?.repository ? [task.repository] : [];
}

// Web backlink to the inbox report that spawned this task, so the
// auto-generated PR can point back at it. Built from the same pieces as the
// report's `_posthogUrl`: <apiUrl>/project/<projectId>/inbox/<reportId>.
function readTaskSource(sources: RunLaunchSources): TaskSource | undefined {
  const signalReportId = sources.task?.signal_report;
  if (!signalReportId) {
    return undefined;
  }
  const { apiUrl, projectId } = sources.config;
  return {
    label: "inbox report",
    url: `${getProjectWebUrl(apiUrl, projectId)}/inbox/${signalReportId}`,
  };
}
