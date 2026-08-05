import { inject, injectable } from "inversify";
import {
  type CanvasBuildActionInput,
  type CanvasBuildLifecycle,
  type CanvasBuildRecord,
  canvasBuildRecordSchema,
} from "./canvasBuildSchemas";
import type {
  CanvasSource,
  CanvasSourceProject,
  CanvasVersion,
  DashboardRecord,
} from "./dashboardSchemas";
import { FREEFORM_TEMPLATE_ID } from "./freeformSchemas";
import { PROJECT_API_CLIENT, type ProjectApiClient } from "./projectApiClient";

// A canvas as the PostHog canvases API returns it.
interface ApiCanvas {
  id: string;
  name: string;
  channel: string;
  template_id: string;
  context: string;
  generation_task_id: string | null;
  pinned_at: string | null;
  current_version_id: string | null;
  published_build_id: string | null;
  created_by?: {
    uuid: string;
    first_name?: string | null;
    last_name?: string | null;
    email?: string | null;
  } | null;
  created_at: string;
  updated_at: string;
}

interface ApiVersion {
  id: string;
  parent_version_id: string | null;
  prompt: string | null;
  task_id: string | null;
  created_by?: ApiCanvas["created_by"];
  created_at: string;
}

function creatorLabel(created_by: ApiCanvas["created_by"]): string | undefined {
  if (!created_by) return undefined;
  const name = [created_by.first_name, created_by.last_name]
    .filter(Boolean)
    .join(" ")
    .trim();
  return name || created_by.email || undefined;
}

function toEpoch(value: string | null | undefined): number | undefined {
  if (!value) return undefined;
  const parsed = Date.parse(value);
  return Number.isNaN(parsed) ? undefined : parsed;
}

function toRecord(api: ApiCanvas): DashboardRecord {
  return {
    id: api.id,
    channelId: api.channel,
    name: api.name,
    templateId: api.template_id || FREEFORM_TEMPLATE_ID,
    context: api.context ?? "",
    generationTaskId: api.generation_task_id,
    createdBy: creatorLabel(api.created_by),
    createdByUuid: api.created_by?.uuid,
    createdAt: toEpoch(api.created_at) ?? 0,
    updatedAt: toEpoch(api.updated_at) ?? 0,
    pinnedAt: toEpoch(api.pinned_at),
    currentVersionId: api.current_version_id,
    publishedBuildId: api.published_build_id,
  };
}

// The snake→camel field mapping for a build row from the builds endpoints.
function buildRecordInput(build: Record<string, unknown>) {
  return {
    id: build.id,
    sourceVersionId: build.source_version_id,
    buildStatus: build.build_status,
    diagnostics: build.diagnostics ?? [],
    manifest: build.manifest ?? null,
    artifactUrl: build.artifact_url,
    pinned: build.pinned,
    createdAt: build.created_at,
    finishedAt: build.finished_at,
  };
}

function toBuildRecord(build: Record<string, unknown>): CanvasBuildRecord {
  return canvasBuildRecordSchema.parse(buildRecordInput(build));
}

function tryToBuildRecord(
  build: Record<string, unknown>,
): CanvasBuildRecord | null {
  const parsed = canvasBuildRecordSchema.safeParse(buildRecordInput(build));
  return parsed.success ? parsed.data : null;
}

/**
 * Canvases backed by the PostHog canvases API. A canvas is a first-class row
 * filed into a backend channel; its source is versioned per publish
 * (source/versions endpoints) and its rendered output is the published
 * build's artifact (builds endpoints).
 */
@injectable()
export class DashboardsService {
  constructor(
    @inject(PROJECT_API_CLIENT)
    private readonly api: ProjectApiClient,
  ) {}

  async list(channelId: string): Promise<DashboardRecord[]> {
    const rows = await this.api.listPaginated<ApiCanvas>(
      `canvases/?channel=${encodeURIComponent(channelId)}`,
      "list canvases",
      { limit: 200 },
    );
    return rows.map(toRecord);
  }

  async get(id: string): Promise<DashboardRecord | null> {
    const res = await this.api.fetch(`canvases/${encodeURIComponent(id)}/`);
    if (res.status === 404) return null;
    if (!res.ok) throw new Error(`Failed to load canvas (${res.status})`);
    return toRecord((await res.json()) as ApiCanvas);
  }

  async create(input: {
    channelId: string;
    name: string;
    templateId?: string;
  }): Promise<DashboardRecord> {
    const api = await this.api.json<ApiCanvas>(`canvases/`, "create canvas", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        channel_id: input.channelId,
        name: input.name,
        template_id: input.templateId ?? FREEFORM_TEMPLATE_ID,
      }),
    });
    return toRecord(api);
  }

  private async patch(
    id: string,
    body: Record<string, unknown>,
    errorLabel: string,
  ): Promise<DashboardRecord> {
    const api = await this.api.json<ApiCanvas>(
      `canvases/${encodeURIComponent(id)}/`,
      errorLabel,
      {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      },
    );
    return toRecord(api);
  }

  // Persist the author-written context (markdown) passed to generation tasks.
  saveContext(input: {
    id: string;
    context: string;
  }): Promise<DashboardRecord> {
    return this.patch(
      input.id,
      { context: input.context },
      "save canvas context",
    );
  }

  // Record (or clear, when taskId is null) the task currently generating this
  // canvas.
  setGenerationTask(input: {
    id: string;
    taskId: string | null;
  }): Promise<DashboardRecord> {
    return this.patch(
      input.id,
      { generation_task_id: input.taskId },
      "set generation task",
    );
  }

  // Pin (or unpin) a canvas to its channel (shared across users).
  setPinned(input: { id: string; pinned: boolean }): Promise<DashboardRecord> {
    return this.patch(input.id, { pinned: input.pinned }, "set pin");
  }

  rename(input: { id: string; name: string }): Promise<DashboardRecord> {
    return this.patch(input.id, { name: input.name }, "rename canvas");
  }

  // Read the canvas's source project — the head, or a historical version.
  async getSource(input: {
    id: string;
    versionId?: string;
  }): Promise<CanvasSource> {
    const suffix = input.versionId
      ? `?version_id=${encodeURIComponent(input.versionId)}`
      : "";
    const body = await this.api.json<{
      project: CanvasSourceProject;
      current_version_id: string | null;
    }>(
      `canvases/${encodeURIComponent(input.id)}/source/${suffix}`,
      "load canvas source",
    );
    return { project: body.project, currentVersionId: body.current_version_id };
  }

  // The canvas's version history, newest first (metadata only).
  async listVersions(id: string): Promise<CanvasVersion[]> {
    const rows = await this.api.listPaginated<ApiVersion>(
      `canvases/${encodeURIComponent(id)}/versions/`,
      "list canvas versions",
      { limit: 100 },
    );
    return rows.map((row) => ({
      id: row.id,
      parentVersionId: row.parent_version_id,
      prompt: row.prompt,
      taskId: row.task_id,
      createdBy: creatorLabel(row.created_by),
      createdAt: toEpoch(row.created_at) ?? 0,
    }));
  }

  // Move the canvas's head back to an existing version and rebuild it.
  async revertToVersion(input: {
    id: string;
    versionId: string;
    expectedCurrentVersionId: string | null;
  }): Promise<CanvasBuildRecord> {
    const build = await this.api.json<Record<string, unknown>>(
      `canvases/${encodeURIComponent(input.id)}/revert/`,
      "revert canvas",
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          version_id: input.versionId,
          expected_current_version_id: input.expectedCurrentVersionId,
        }),
      },
    );
    return toBuildRecord(build);
  }

  // Read a canvas's build lifecycle (pointers + recent builds). Publishing
  // queues a build server-side; callers poll this until it settles.
  async getBuilds(id: string): Promise<CanvasBuildLifecycle> {
    const body = await this.api.json<{
      published_build_id: string | null;
      current_version_id: string | null;
      builds: Record<string, unknown>[];
    }>(`canvases/${encodeURIComponent(id)}/builds/`, "load canvas builds");
    // Each build row is already validated by tryToBuildRecord; this endpoint is
    // polled every couple of seconds during builds, so don't re-run the whole
    // lifecycle schema (which would zod-parse every record a second time).
    return {
      publishedBuildId: body.published_build_id ?? null,
      currentVersionId: body.current_version_id ?? null,
      builds: body.builds
        .map(tryToBuildRecord)
        .filter((build): build is CanvasBuildRecord => build !== null),
    };
  }

  async actOnBuild(input: CanvasBuildActionInput): Promise<CanvasBuildRecord> {
    const build = await this.api.json<Record<string, unknown>>(
      `canvases/${encodeURIComponent(input.id)}/builds/action/`,
      "update canvas build",
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ action: input.action, build_id: input.buildId }),
      },
    );
    return toBuildRecord(build);
  }

  async delete(id: string): Promise<void> {
    const res = await this.api.fetch(`canvases/${encodeURIComponent(id)}/`, {
      method: "DELETE",
    });
    // Already gone is a successful delete; surface anything else.
    if (!res.ok && res.status !== 404) {
      throw new Error(`Failed to delete canvas (${res.status})`);
    }
  }
}
