import { inject, injectable } from "inversify";
import {
  type CanvasBuildActionInput,
  type CanvasBuildLifecycle,
  type CanvasBuildRecord,
  canvasBuildRecordSchema,
} from "./canvasBuildSchemas";
import type {
  CanvasActionDefinition,
  CanvasActionResult,
  CanvasDraft,
  CanvasSource,
  CanvasSourceProject,
  CanvasStateEntry,
  CanvasStateScope,
  CanvasVersion,
  DashboardRecord,
} from "./dashboardSchemas";
import {
  type CanvasAgentRequestResult,
  canvasAgentRequestResultSchema,
  FREEFORM_TEMPLATE_ID,
} from "./freeformSchemas";
import {
  type CanvasLayout,
  type CanvasLayoutResult,
  componentMetaSchema,
  type LayoutOperation,
} from "./gridLayoutSchemas";
import {
  PROJECT_API_CLIENT,
  type ProjectApiClient,
  ProjectApiError,
} from "./projectApiClient";

// A canvas as the PostHog canvases API returns it.
interface ApiCanvas {
  id: string;
  name: string;
  kind?: "freeform" | "grid" | "component";
  description?: string;
  component_meta?: unknown;
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

interface ApiDraft {
  version_id: string;
  prompt: string | null;
  created_by?: ApiCanvas["created_by"];
  created_at: string;
  build_status: "queued" | "building" | "ready" | "failed" | null;
  build_id: string | null;
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
  // Fail-soft on the contract shape: a meta this client doesn't understand
  // renders as "not placeable", never a crashed record list.
  const meta = componentMetaSchema.safeParse(api.component_meta);
  return {
    id: api.id,
    channelId: api.channel,
    name: api.name,
    kind: api.kind ?? "freeform",
    description: api.description ?? "",
    componentMeta: meta.success ? meta.data : null,
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

  // The component store: component-kind canvases across every channel visible
  // to the caller, optionally narrowed by a name/description search.
  async listComponents(input: { search?: string }): Promise<DashboardRecord[]> {
    const search = input.search
      ? `&search=${encodeURIComponent(input.search)}`
      : "";
    const rows = await this.api.listPaginated<ApiCanvas>(
      `canvases/?kind=component${search}`,
      "list canvas components",
      { limit: 200 },
    );
    return rows.map(toRecord);
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

  // Get-or-create the caller's home canvas: a grid canvas in their personal
  // channel, pointed at by their home preference. Idempotent.
  async home(): Promise<DashboardRecord> {
    const api = await this.api.json<ApiCanvas>(
      `canvases/home/`,
      "provision home canvas",
      { method: "POST" },
    );
    return toRecord(api);
  }

  // Read a grid canvas's layout document — the head, or a historical version.
  async getLayout(input: {
    id: string;
    versionId?: string;
  }): Promise<CanvasLayoutResult> {
    const suffix = input.versionId
      ? `?version_id=${encodeURIComponent(input.versionId)}`
      : "";
    const body = await this.api.json<{
      layout: CanvasLayout;
      current_version_id: string | null;
    }>(
      `canvases/${encodeURIComponent(input.id)}/layout/${suffix}`,
      "load canvas layout",
    );
    return { layout: body.layout, currentVersionId: body.current_version_id };
  }

  // Publish a complete layout document as the grid canvas's new head. Live
  // immediately — layout is data, no build runs.
  async publishLayout(input: {
    id: string;
    layout: CanvasLayout;
    prompt?: string;
    expectedCurrentVersionId: string | null;
  }): Promise<CanvasLayoutResult> {
    const body = await this.api.json<{
      layout: CanvasLayout;
      current_version_id: string;
    }>(
      `canvases/${encodeURIComponent(input.id)}/layout/publish/`,
      "publish canvas layout",
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          layout: input.layout,
          prompt: input.prompt,
          expected_current_version_id: input.expectedCurrentVersionId,
        }),
      },
    );
    return { layout: body.layout, currentVersionId: body.current_version_id };
  }

  // Apply surgical operations to the grid canvas's current layout — the
  // default write path, guarded so concurrent edits conflict (409) instead of
  // silently merging.
  async patchLayout(input: {
    id: string;
    operations: LayoutOperation[];
    prompt?: string;
    expectedCurrentVersionId: string | null;
  }): Promise<CanvasLayoutResult> {
    const body = await this.api.json<{
      layout: CanvasLayout;
      current_version_id: string;
    }>(
      `canvases/${encodeURIComponent(input.id)}/layout/patch/`,
      "patch canvas layout",
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          operations: input.operations,
          prompt: input.prompt,
          expected_current_version_id: input.expectedCurrentVersionId,
        }),
      },
    );
    return { layout: body.layout, currentVersionId: body.current_version_id };
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

  file(input: { id: string; channelId: string }): Promise<DashboardRecord> {
    return this.patch(
      input.id,
      { channel_id: input.channelId },
      "file canvas to space",
    );
  }

  // File a rendering error in the canvas's authoring-task thread (the server
  // dedupes per build and error type). Best-effort: a report must never affect
  // the render, and backends without the endpoint just refuse it, so every
  // failure is swallowed.
  async reportError(input: {
    id: string;
    buildId: string;
    errorType: string;
  }): Promise<void> {
    try {
      await this.api.fetch(
        `canvases/${encodeURIComponent(input.id)}/report_error/`,
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            build_id: input.buildId,
            error_type: input.errorType,
          }),
        },
      );
    } catch {
      // Advisory call — rendering carries on regardless.
    }
  }

  // The canvas's readable ph.state entries: shared ones plus the caller's own
  // user-scoped ones. Optionally narrowed to one scope.
  async listState(input: {
    id: string;
    scope?: CanvasStateScope;
  }): Promise<CanvasStateEntry[]> {
    const suffix = input.scope
      ? `?scope=${encodeURIComponent(input.scope)}`
      : "";
    const body = await this.api.json<{
      entries: Array<{
        scope: CanvasStateScope;
        key: string;
        value: unknown;
        updated_at: string;
      }>;
    }>(
      `canvases/${encodeURIComponent(input.id)}/state/${suffix}`,
      "read canvas state",
    );
    return body.entries.map((entry) => ({
      scope: entry.scope,
      key: entry.key,
      value: entry.value,
      updatedAt: entry.updated_at,
    }));
  }

  // Write one ph.state key; a null value deletes it (the 204 path).
  async setState(input: {
    id: string;
    scope: CanvasStateScope;
    key: string;
    value: unknown;
  }): Promise<void> {
    const res = await this.api.fetch(
      `canvases/${encodeURIComponent(input.id)}/state/set/`,
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          scope: input.scope,
          key: input.key,
          value: input.value ?? null,
        }),
      },
    );
    if (!res.ok) {
      const detail = await res
        .json()
        .then((body) => (body as { detail?: string }).detail ?? null)
        .catch(() => null);
      throw new ProjectApiError(
        detail ?? `Failed to write canvas state (${res.status})`,
        res.status,
      );
    }
  }

  // The action registry: every verb a canvas may declare and invoke.
  async listActions(): Promise<CanvasActionDefinition[]> {
    const body = await this.api.json<{ actions: CanvasActionDefinition[] }>(
      `canvases/actions/`,
      "list canvas actions",
    );
    return body.actions;
  }

  // Invoke one registered action verb as the viewer.
  async invokeAction(input: {
    id: string;
    verb: string;
    payload: Record<string, unknown>;
  }): Promise<CanvasActionResult> {
    const res = await this.api.fetch(
      `canvases/${encodeURIComponent(input.id)}/actions/invoke/`,
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ verb: input.verb, payload: input.payload }),
      },
    );
    const body = (await res.json().catch(() => ({}))) as {
      detail?: string;
      verb?: string;
      result?: Record<string, unknown>;
    };
    if (!res.ok) {
      throw new ProjectApiError(
        body.detail ?? `Failed to invoke canvas action (${res.status})`,
        res.status,
      );
    }
    return { verb: body.verb ?? input.verb, result: body.result ?? {} };
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

  // The canvas's staged drafts, newest first, each with its latest build status.
  async listDrafts(id: string): Promise<CanvasDraft[]> {
    const rows = await this.api.json<ApiDraft[]>(
      `canvases/${encodeURIComponent(id)}/drafts/`,
      "list canvas drafts",
    );
    return rows.map((row) => ({
      versionId: row.version_id,
      prompt: row.prompt,
      createdBy: creatorLabel(row.created_by),
      createdAt: toEpoch(row.created_at) ?? 0,
      buildStatus: row.build_status,
      buildId: row.build_id,
    }));
  }

  // Make a draft version the canvas's live head (adopting its ready build, or
  // rebuilding when the artifacts aged out). Returns the now-live build.
  async promoteDraft(input: {
    id: string;
    versionId: string;
    expectedCurrentVersionId: string | null;
  }): Promise<CanvasBuildRecord> {
    const build = await this.api.json<Record<string, unknown>>(
      `canvases/${encodeURIComponent(input.id)}/promote/`,
      "promote canvas draft",
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
  async getBuilds(input: {
    id: string;
    versionId?: string;
  }): Promise<CanvasBuildLifecycle> {
    const suffix = input.versionId
      ? `?version_id=${encodeURIComponent(input.versionId)}`
      : "";
    const body = await this.api.json<{
      published_build_id: string | null;
      current_version_id: string | null;
      builds: Record<string, unknown>[];
    }>(
      `canvases/${encodeURIComponent(input.id)}/builds/${suffix}`,
      "load canvas builds",
    );
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

  async requestAgent(input: {
    id: string;
    prompt: string;
  }): Promise<CanvasAgentRequestResult> {
    const res = await this.api.fetch(
      `canvases/${encodeURIComponent(input.id)}/request_agent/`,
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ prompt: input.prompt }),
      },
    );
    const body = (await res.json().catch(() => ({}))) as {
      detail?: string;
      request_outcome?: string;
      task_id?: string;
    };
    // The backend answers quota, capability, and missing-task refusals with a
    // structured `detail`; surface it so the viewer sees the reason, not a bare
    // status code.
    if (!res.ok) {
      throw new ProjectApiError(
        body.detail ?? `Failed to request canvas agent (${res.status})`,
        res.status,
      );
    }
    return canvasAgentRequestResultSchema.parse({
      requestOutcome: body.request_outcome,
      taskId: body.task_id,
    });
  }
}
