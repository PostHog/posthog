import type {
  ArtifactType,
  Task,
  TaskRun,
  TaskRunArtifact,
  TaskRunArtifactMetadata,
  TaskRunStatus,
} from "@posthog/shared/domain-types";
import type { Schemas } from "./generated";

type TaskRunResponseDTO = Partial<
  Omit<Schemas.TaskRunDetail, "artifacts" | "status">
> & {
  id: string;
  artifacts?: Array<
    Schemas.TaskRunArtifactResponse & { metadata?: unknown }
  > | null;
  status?: Schemas.StatusA35Enum | "started" | null;
  team?: number | null;
};

type TaskResponseDTO = Partial<
  Omit<Schemas.Task, "created_by" | "json_schema" | "latest_run">
> & {
  id: string;
  channel?: string | null;
  created_by?: Schemas.UserBasic | null;
  github_user_integration?: string | null;
  json_schema?: unknown | null;
  latest_run?: Record<string, unknown> | null;
  runtime?: unknown;
};

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function isTaskRunResponseDTO(value: unknown): value is TaskRunResponseDTO {
  return isRecord(value) && typeof value.id === "string";
}

function normalizeTaskRunStatus(status: unknown): TaskRunStatus {
  switch (status) {
    case "started":
      return "in_progress";
    case "not_started":
    case "queued":
    case "in_progress":
    case "completed":
    case "failed":
    case "cancelled":
      return status;
    default:
      return "not_started";
  }
}

function normalizeArtifactType(type: string): ArtifactType {
  switch (type) {
    case "plan":
    case "context":
    case "reference":
    case "output":
    case "artifact":
    case "user_attachment":
    case "skill_bundle":
      return type;
    default:
      return "artifact";
  }
}

function normalizeArtifactMetadata(
  value: unknown,
): TaskRunArtifactMetadata | undefined {
  if (
    !isRecord(value) ||
    typeof value.skill_name !== "string" ||
    (value.skill_source !== "user" &&
      value.skill_source !== "repo" &&
      value.skill_source !== "marketplace" &&
      value.skill_source !== "codex")
  ) {
    return undefined;
  }
  if (
    typeof value.content_sha256 !== "string" ||
    value.bundle_format !== "zip" ||
    typeof value.schema_version !== "number"
  ) {
    return undefined;
  }

  return {
    skill_name: value.skill_name,
    skill_source: value.skill_source,
    content_sha256: value.content_sha256,
    bundle_format: value.bundle_format,
    schema_version: value.schema_version,
  };
}

function normalizeTaskRunArtifact(
  artifact: NonNullable<TaskRunResponseDTO["artifacts"]>[number],
): TaskRunArtifact {
  const metadata = normalizeArtifactMetadata(artifact.metadata);

  return {
    ...(artifact.id === undefined ? {} : { id: artifact.id }),
    name: artifact.name,
    type: normalizeArtifactType(artifact.type),
    ...(artifact.source === undefined ? {} : { source: artifact.source }),
    ...(artifact.size === undefined ? {} : { size: artifact.size }),
    ...(artifact.content_type === undefined
      ? {}
      : { content_type: artifact.content_type }),
    ...(metadata === undefined ? {} : { metadata }),
    ...(artifact.storage_path === undefined
      ? {}
      : { storage_path: artifact.storage_path }),
    ...(artifact.uploaded_at === undefined
      ? {}
      : { uploaded_at: artifact.uploaded_at }),
  };
}

export function normalizeTaskRunResponse(
  dto: TaskRunResponseDTO,
  context: { teamId: number; taskId?: string },
): TaskRun {
  return {
    id: dto.id,
    task: dto.task ?? context.taskId ?? "",
    team: dto.team ?? context.teamId,
    branch: dto.branch ?? null,
    ...(dto.runtime_adapter === undefined
      ? {}
      : { runtime_adapter: dto.runtime_adapter }),
    ...(dto.model === undefined ? {} : { model: dto.model }),
    ...(dto.reasoning_effort === undefined
      ? {}
      : { reasoning_effort: dto.reasoning_effort }),
    ...(dto.stage === undefined ? {} : { stage: dto.stage }),
    ...(dto.environment === undefined ? {} : { environment: dto.environment }),
    status: normalizeTaskRunStatus(dto.status),
    log_url: dto.log_url ?? "",
    error_message: dto.error_message ?? null,
    output: isRecord(dto.output) ? dto.output : null,
    state: isRecord(dto.state) ? dto.state : {},
    ...(dto.artifacts == null
      ? {}
      : { artifacts: dto.artifacts.map(normalizeTaskRunArtifact) }),
    created_at: dto.created_at ?? "",
    updated_at: dto.updated_at ?? "",
    completed_at: dto.completed_at ?? null,
  };
}

export function normalizeTaskResponse(
  dto: TaskResponseDTO,
  context: { teamId: number },
): Task {
  const jsonSchema = isRecord(dto.json_schema) ? dto.json_schema : null;
  const runtime =
    dto.runtime === "acp" || dto.runtime === "pi" ? dto.runtime : undefined;

  const latestRun = isTaskRunResponseDTO(dto.latest_run)
    ? normalizeTaskRunResponse(dto.latest_run, {
        teamId: context.teamId,
        taskId: dto.id,
      })
    : undefined;

  return {
    id: dto.id,
    task_number: dto.task_number ?? null,
    slug: dto.slug ?? "",
    title: dto.title ?? "",
    ...(dto.title_manually_set === undefined
      ? {}
      : { title_manually_set: dto.title_manually_set }),
    description: dto.description ?? "",
    created_at: dto.created_at ?? "",
    updated_at: dto.updated_at ?? "",
    ...(dto.created_by === undefined ? {} : { created_by: dto.created_by }),
    origin_product: dto.origin_product ?? "",
    ...(dto.repository === undefined ? {} : { repository: dto.repository }),
    ...(dto.github_integration === undefined
      ? {}
      : { github_integration: dto.github_integration }),
    ...(dto.github_user_integration === undefined
      ? {}
      : { github_user_integration: dto.github_user_integration }),
    ...(dto.json_schema === undefined ? {} : { json_schema: jsonSchema }),
    ...(dto.signal_report === undefined
      ? {}
      : { signal_report: dto.signal_report }),
    ...(dto.internal === undefined ? {} : { internal: dto.internal }),
    ...(runtime === undefined ? {} : { runtime }),
    ...(dto.channel === undefined ? {} : { channel: dto.channel }),
    ...(latestRun === undefined ? {} : { latest_run: latestRun }),
  };
}
