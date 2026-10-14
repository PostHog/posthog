import type { EffortLevel } from "@posthog/shared/domain-types";

export namespace LoopSchemas {
  export type LoopTriggerTypeEnum = "schedule" | "github";
  export type LoopRuntimeAdapterEnum = "claude" | "codex";
  export type LoopReasoningEffortEnum = EffortLevel;
  export type LoopGithubTriggerEventEnum =
    | "issues"
    | "issue_comment"
    | "pull_request"
    | "push";
  export type LoopRunStatusEnum =
    | "not_started"
    | "queued"
    | "in_progress"
    | "completed"
    | "failed"
    | "cancelled";
  export type LoopRunEnvironmentEnum = "local" | "cloud";

  export type LoopRepositoryEntry = {
    github_integration_id: number;
    full_name: string;
  };

  export type LoopNotificationChannel = {
    enabled: boolean;
    params: Record<string, unknown>;
  };

  export type LoopNotifications = {
    email: LoopNotificationChannel;
    slack: LoopNotificationChannel;
  };

  export type LoopContextTarget = {
    channel_id: string;
    name: string;
  };

  export type LoopScheduleTriggerConfig = {
    cron_expression?: string;
    timezone?: string;
    run_at?: string;
  };

  export type LoopGithubTriggerFilters = {
    actions?: Array<string>;
  };

  export type LoopGithubTriggerConfig = {
    github_integration_id: number;
    repository: string;
    events: Array<LoopGithubTriggerEventEnum>;
    filters?: LoopGithubTriggerFilters;
  };

  export type LoopTriggerConfig =
    | LoopScheduleTriggerConfig
    | LoopGithubTriggerConfig;

  export type LoopTrigger = {
    id: string;
    loop_id: string;
    type: LoopTriggerTypeEnum;
    enabled: boolean;
    config: LoopTriggerConfig;
    created_at: string;
    updated_at: string;
  };

  export type Loop = {
    id: string;
    team_id: number;
    created_by_id: number | null;
    name: string;
    description: string;
    instructions: string;
    runtime_adapter: LoopRuntimeAdapterEnum;
    model: string;
    reasoning_effort: LoopReasoningEffortEnum | null;
    repositories: Array<LoopRepositoryEntry>;
    enabled: boolean;
    notifications: LoopNotifications;
    context_target: LoopContextTarget | null;
    last_run_at: string | null;
    last_run_status: string | null;
    created_at: string;
    updated_at: string;
    triggers: Array<LoopTrigger>;
  };

  export type LoopRun = {
    id: string;
    task_id: string;
    status: LoopRunStatusEnum;
    environment: LoopRunEnvironmentEnum;
    branch: string | null;
    error_message: string | null;
    output: Record<string, unknown> | null;
    created_at: string;
    completed_at: string | null;
  };
}
