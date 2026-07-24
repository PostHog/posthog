// PostHog Task model (matches the desktop task API's OpenAPI schema)
import type { AgentRuntime } from "./agent-runtime";
import type { UploadableSkillSource } from "./skills";

export interface Task {
  id: string;
  task_number?: number;
  slug?: string;
  title: string;
  description: string;
  origin_product:
    | "error_tracking"
    | "eval_clusters"
    | "user_created"
    | "support_queue"
    | "session_summaries"
    | "signal_report"
    | "signals_scout"
    | "slack";
  signal_report?: string | null; // Inbox report UUID when origin_product is "signal_report"
  github_integration?: number | null;
  repository: string; // Format: "organization/repository" (e.g., "posthog/posthog-js")
  json_schema?: Record<string, unknown> | null; // JSON schema for task output validation
  internal?: boolean;
  runtime?: AgentRuntime;
  created_at: string;
  updated_at: string;
  created_by?: {
    id: number;
    uuid: string;
    distinct_id: string;
    first_name: string;
    email: string;
  };
  latest_run?: TaskRun;
}

export type ArtifactType =
  | "plan"
  | "context"
  | "reference"
  | "output"
  | "artifact"
  | "user_attachment"
  | "skill_bundle";

export interface TaskRunArtifactMetadata {
  skill_name: string;
  skill_source: UploadableSkillSource;
  content_sha256: string;
  bundle_format: "zip";
  schema_version: number;
}

export interface TaskRunArtifact {
  id?: string;
  name: string;
  type: ArtifactType;
  source?: string;
  size?: number;
  content_type?: string;
  metadata?: TaskRunArtifactMetadata;
  storage_path?: string;
  uploaded_at?: string;
}

export type TaskRunStatus =
  | "not_started"
  | "queued"
  | "in_progress"
  | "completed"
  | "failed"
  | "cancelled";

export type TaskRunEnvironment = "local" | "cloud";

// TaskRun model - represents individual execution runs of tasks
export interface TaskRun {
  id: string;
  task: string; // Task ID
  team: number;
  branch: string | null;
  stage: string | null; // Current stage (e.g., 'research', 'plan', 'build')
  environment: TaskRunEnvironment;
  status: TaskRunStatus;
  log_url: string;
  error_message: string | null;
  output: Record<string, unknown> | null; // Structured output (PR URL, commit SHA, etc.)
  state: Record<string, unknown>; // Intermediate run state (defaults to {}, never null)
  artifacts?: TaskRunArtifact[];
  created_at: string;
  updated_at: string;
  completed_at: string | null;
}

export interface PostHogAPIConfig {
  apiUrl: string;
  getApiKey: () => string | Promise<string>;
  refreshApiKey?: () => string | Promise<string>;
  projectId: number;
  userAgent?: string;
}
