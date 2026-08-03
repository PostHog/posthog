import {
  CANVAS_COMPONENT_PATH,
  CANVAS_ENTRY_HTML,
  CANVAS_SOURCE_SCHEMA_VERSION,
} from "@posthog/shared";
import { inject, injectable } from "inversify";
import {
  type CanvasBuildActionInput,
  type CanvasBuildLifecycle,
  type CanvasBuildRecord,
  canvasBuildLifecycleSchema,
  canvasBuildRecordSchema,
} from "./canvasBuildSchemas";
import type {
  CanvasSource,
  CanvasSourceProject,
  CanvasVersion,
  DashboardRecord,
} from "./dashboardSchemas";
import { FREEFORM_TEMPLATE_ID } from "./freeformSchemas";
import {
  apiErrorStatus,
  PROJECT_API_CLIENT,
  type ProjectApiClient,
} from "./projectApiClient";

// Display name (canvas h1) of a channel's auto-created home canvas.
const HOME_CANVAS_NAME = "Home";

// The entry shell for a client-authored single-file project (the home canvas
// seed): the runtime mounts the default export of the canvas component file.
const SINGLE_FILE_INDEX_HTML = `<!doctype html>
<html>
  <head>
    <meta charset="utf-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1" />
  </head>
  <body>
    <div id="root"></div>
    <script type="module" src="/${CANVAS_COMPONENT_PATH}"></script>
  </body>
</html>
`;

// A canvas as the PostHog canvases API returns it.
interface ApiCanvas {
  id: string;
  name: string;
  channel: string;
  template_id: string;
  context: string;
  generation_task_id: string | null;
  pinned_at: string | null;
  is_home: boolean;
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
    isHome: api.is_home,
    currentVersionId: api.current_version_id,
    publishedBuildId: api.published_build_id,
  };
}

function toBuildRecord(build: Record<string, unknown>): CanvasBuildRecord {
  return canvasBuildRecordSchema.parse({
    id: build.id,
    sourceVersionId: build.source_version_id,
    buildStatus: build.build_status,
    diagnostics: build.diagnostics ?? [],
    manifest: build.manifest ?? null,
    artifactUrl: build.artifact_url,
    pinned: build.pinned,
    createdAt: build.created_at,
    finishedAt: build.finished_at,
  });
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
    isHome?: boolean;
  }): Promise<DashboardRecord> {
    const api = await this.api.json<ApiCanvas>(`canvases/`, "create canvas", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        channel_id: input.channelId,
        name: input.name,
        template_id: input.templateId ?? FREEFORM_TEMPLATE_ID,
        is_home: input.isHome ?? false,
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
    const rows = await this.api.json<ApiVersion[]>(
      `canvases/${encodeURIComponent(id)}/versions/`,
      "list canvas versions",
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
  }): Promise<CanvasBuildRecord> {
    const build = await this.api.json<Record<string, unknown>>(
      `canvases/${encodeURIComponent(input.id)}/revert/`,
      "revert canvas",
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ version_id: input.versionId }),
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
    return canvasBuildLifecycleSchema.parse({
      publishedBuildId: body.published_build_id,
      currentVersionId: body.current_version_id,
      builds: body.builds.map(toBuildRecord),
    });
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

  // Ensure the channel has a home canvas: the freeform board shown when the
  // channel opens. Idempotent — reuses the channel's existing home canvas, and
  // seeds its source (via a real publish, so it gets built) when empty.
  async ensureHomeCanvas(channelId: string): Promise<DashboardRecord> {
    let record = await this.findHomeCanvas(channelId);
    if (!record) {
      try {
        record = await this.create({
          channelId,
          name: HOME_CANVAS_NAME,
          templateId: FREEFORM_TEMPLATE_ID,
          isHome: true,
        });
      } catch (error) {
        // Only the is_home uniqueness race (409) means another client created
        // it; reuse theirs. Any other failure (auth, capacity, network) must
        // surface, not be masked as a race.
        if (apiErrorStatus(error) !== 409) throw error;
        record = await this.findHomeCanvas(channelId);
        if (!record) throw new Error("Failed to create home canvas");
      }
    }
    if (!record.currentVersionId) {
      record = await this.publishHomeSeed(record, channelId);
    }
    return record;
  }

  // Rebuild a channel's home canvas from the default template. Non-destructive:
  // the pre-reset source stays in the version history, so a revert restores it.
  async resetHomeCanvas(channelId: string): Promise<DashboardRecord> {
    const record = await this.findHomeCanvas(channelId);
    if (!record) return this.ensureHomeCanvas(channelId);
    return this.publishHomeSeed(record, channelId);
  }

  private async findHomeCanvas(
    channelId: string,
  ): Promise<DashboardRecord | null> {
    const rows = await this.api.listPaginated<ApiCanvas>(
      `canvases/?channel=${encodeURIComponent(channelId)}&is_home=true`,
      "find home canvas",
      { limit: 200 },
    );
    return rows.length ? toRecord(rows[0]) : null;
  }

  // Publish the generated home board as the canvas's new head version. The
  // board queries system.canvases/system.tasks ad hoc, so inline queries are
  // declared as a capability.
  private async publishHomeSeed(
    record: DashboardRecord,
    channelId: string,
  ): Promise<DashboardRecord> {
    const project = {
      schemaVersion: CANVAS_SOURCE_SCHEMA_VERSION,
      files: {
        [CANVAS_ENTRY_HTML]: SINGLE_FILE_INDEX_HTML,
        [CANVAS_COMPONENT_PATH]: buildHomeCanvasCode(channelId, record.id),
      },
      entryHtml: CANVAS_ENTRY_HTML,
      dependencies: { react: "19.0.0" },
      canvasSdkVersion: "0.1.0",
      capabilities: {
        posthog: { insights: [], inlineQueries: true, captureEvents: [] },
        network: { origins: [] },
      },
    };
    const publish = (expectedVersionId: string | null) =>
      this.api.json<unknown>(
        `canvases/${encodeURIComponent(record.id)}/publish/`,
        "seed home canvas",
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            project,
            prompt: "Default home board",
            expected_current_version_id: expectedVersionId,
          }),
        },
      );
    try {
      await publish(record.currentVersionId ?? null);
    } catch (error) {
      // A concurrent seed can win the guarded publish between our read and
      // POST. On the 409 version conflict, re-read the head and retry once
      // against the fresh version id rather than failing the channel open.
      if (apiErrorStatus(error) !== 409) throw error;
      const conflicted = await this.get(record.id);
      await publish(conflicted?.currentVersionId ?? null);
    }
    const fresh = await this.get(record.id);
    return fresh ?? record;
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

// The seeded React source for a channel's home canvas. It runs in the freeform
// sandbox (null-origin iframe), so its only data avenue is `window.ph.query`
// (HogQL). It reads its lists from the `system.canvases`/`system.tasks` HogQL tables:
//   - Canvases: this channel's canvases (excluding the home canvas).
//   - Inbox / to-dos: stubbed (no data source yet) with an assignee filter.
//   - Tasks: this channel's tasks, newest first.
// Each list shows a page at a time and loads more as its own box is scrolled.
// Rows and the "New" buttons drive host routing via the allowlisted
// `ph.navigate` bridge (toTask/toNewTask/toCanvas/toNewCanvas); the Inbox stub
// stays a no-op until it has a data source. channelId is host-supplied, so the
// canvas can only navigate within its own channel; homeCanvasId lets the
// Canvases list exclude this board.
function buildHomeCanvasCode(channelId: string, homeCanvasId: string): string {
  const cid = JSON.stringify(channelId);
  const hid = JSON.stringify(homeCanvasId);
  return `import { useCallback, useEffect, useRef, useState } from "react";

const CHANNEL_ID = ${cid};
const HOME_CANVAS_ID = ${hid};
const PAGE_SIZE = 10;

const ph = (window as any).ph;

// Single-quote a value for inlining into a HogQL string literal.
function sql(v: string): string {
  return "'" + String(v).replace(/'/g, "''") + "'";
}

type Row = { id: string; title: string; createdAt: string };

// Paginated reader for the channel's canvases or tasks, newest first.
function useChannelRows(kind: "dashboard" | "task") {
  const [rows, setRows] = useState<Row[]>([]);
  const [loading, setLoading] = useState(false);
  const [done, setDone] = useState(false);
  const offsetRef = useRef(0);
  const busyRef = useRef(false);

  const loadMore = useCallback(async () => {
    if (busyRef.current || done) return;
    busyRef.current = true;
    setLoading(true);
    try {
      const page = " ORDER BY created_at DESC LIMIT " + PAGE_SIZE + " OFFSET " + offsetRef.current;
      const query =
        kind === "dashboard"
          ? "SELECT id, name, created_at FROM system.canvases" +
            " WHERE channel_id = " + sql(CHANNEL_ID) +
            " AND id != " + sql(HOME_CANVAS_ID) + page
          : "SELECT id, title, created_at FROM system.tasks" +
            " WHERE channel_id = " + sql(CHANNEL_ID) + page;
      const res = await ph.query(query);
      const batch: Row[] = ((res && res.results) || []).map((r: any[]) => ({
        id: String(r[0]),
        title: String(r[1]),
        createdAt: String(r[2]),
      }));
      offsetRef.current += batch.length;
      setRows((prev) => prev.concat(batch));
      if (batch.length < PAGE_SIZE) setDone(true);
    } catch (err) {
      // Stop paging on error (e.g. the system table isn't available yet) rather
      // than spinning; the section just shows what it has.
      setDone(true);
    } finally {
      busyRef.current = false;
      setLoading(false);
    }
  }, [kind, done]);

  useEffect(() => {
    void loadMore();
    // Load the first page once on mount.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  return { rows, loadMore, loading, done };
}

// A fixed-height, scrollable section card. A sentinel at the bottom (observed
// against THIS box, not the page) fires onLoadMore as the user scrolls near the
// end. Styled to match the PostHog app: greenish-gray neutrals, soft
// shadow, ~16px radius, a per-section accent dot.
function Section(props: {
  title: string;
  accent: string;
  onNew: () => void;
  loading: boolean;
  done: boolean;
  onLoadMore: () => void;
  children: any;
  // A "+ New" that isn't wired yet: disable it and explain via tooltip rather
  // than offering a button that silently does nothing.
  newDisabled?: boolean;
  newTooltip?: string;
}) {
  const scrollRef = useRef<HTMLDivElement | null>(null);
  const sentinelRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    const root = scrollRef.current;
    const target = sentinelRef.current;
    if (!root || !target) return;
    const io = new IntersectionObserver(
      (entries) => {
        if (entries.some((e) => e.isIntersecting)) props.onLoadMore();
      },
      { root, rootMargin: "120px" },
    );
    io.observe(target);
    return () => io.disconnect();
  }, [props.onLoadMore]);

  return (
    <section
      style={{
        flex: "1 1 0",
        minWidth: 0,
        maxWidth: 380,
        height: 460,
        display: "flex",
        flexDirection: "column",
        background: "var(--card-bg)",
        border: "1px solid var(--card-border)",
        borderRadius: 16,
        overflow: "hidden",
        boxShadow:
          "0 1px 2px rgba(13,13,13,0.04), 0 12px 32px rgba(13,13,13,0.06)",
      }}
    >
      <header
        style={{
          display: "flex",
          alignItems: "center",
          justifyContent: "space-between",
          padding: "14px 16px",
          borderBottom: "1px solid var(--header-border)",
        }}
      >
        <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
          <span
            style={{
              width: 8,
              height: 8,
              borderRadius: 999,
              background: props.accent,
              boxShadow: "0 0 0 3px " + props.accent + "22",
            }}
          />
          <h2
            style={{
              margin: 0,
              fontSize: 15,
              fontWeight: 600,
              color: "var(--title)",
              letterSpacing: "-0.01em",
            }}
          >
            {props.title}
          </h2>
        </div>
        <button
          type="button"
          className="ph-btn"
          onClick={props.onNew}
          disabled={props.newDisabled}
          title={props.newTooltip}
          style={{
            fontSize: 12,
            fontWeight: 500,
            padding: "4px 10px",
            borderRadius: 8,
            border: "1px solid var(--btn-border)",
            background: "var(--btn-bg)",
            color: "var(--btn-color)",
            cursor: props.newDisabled ? "not-allowed" : "pointer",
            opacity: props.newDisabled ? 0.5 : 1,
          }}
        >
          + New
        </button>
      </header>
      <div ref={scrollRef} style={{ flex: 1, overflowY: "auto", padding: 8 }}>
        {props.children}
        {!props.done ? (
          <div ref={sentinelRef} style={{ height: 1 }} />
        ) : null}
        {props.loading ? (
          <div style={{ padding: 8, fontSize: 12, color: "var(--meta)" }}>Loading…</div>
        ) : null}
      </div>
    </section>
  );
}

function ListRow(props: { title: string; meta?: string; onClick?: () => void }) {
  return (
    <div
      className="ph-row"
      role={props.onClick ? "button" : undefined}
      tabIndex={props.onClick ? 0 : undefined}
      onClick={props.onClick}
      onKeyDown={(e) => {
        if (props.onClick && (e.key === "Enter" || e.key === " ")) {
          e.preventDefault();
          props.onClick();
        }
      }}
      style={{
        padding: "8px 10px",
        borderRadius: 8,
        fontSize: 13,
        color: "var(--row-color)",
        display: "flex",
        justifyContent: "space-between",
        gap: 8,
        cursor: props.onClick ? "pointer" : "default",
      }}
    >
      <span style={{ overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
        {props.title}
      </span>
      {props.meta ? (
        <span style={{ color: "var(--meta)", fontSize: 11, flexShrink: 0 }}>{props.meta}</span>
      ) : null}
    </div>
  );
}

function Empty(props: { label: string }) {
  return (
    <div
      style={{
        display: "flex",
        height: "100%",
        minHeight: 120,
        alignItems: "center",
        justifyContent: "center",
        textAlign: "center",
        padding: 16,
        fontSize: 12,
        color: "var(--empty)",
      }}
    >
      {props.label}
    </div>
  );
}

function CanvasesSection() {
  const { rows, loadMore, loading, done } = useChannelRows("dashboard");
  return (
    <Section
      title="Canvases"
      accent="#f54d00"
      onNew={() => ph.navigate?.toNewCanvas()}
      loading={loading}
      done={done}
      onLoadMore={loadMore}
    >
      {rows.length === 0 && done ? <Empty label="No canvases yet." /> : null}
      {rows.map((r) => (
        <ListRow key={r.id} title={r.title} onClick={() => ph.navigate?.toCanvas(r.id)} />
      ))}
    </Section>
  );
}

function TasksSection() {
  const { rows, loadMore, loading, done } = useChannelRows("task");
  return (
    <Section
      title="Tasks"
      accent="#f8be2a"
      onNew={() => ph.navigate?.toNewTask()}
      loading={loading}
      done={done}
      onLoadMore={loadMore}
    >
      {rows.length === 0 && done ? <Empty label="No tasks yet." /> : null}
      {rows.map((r) => (
        <ListRow
          key={r.id}
          title={r.title}
          meta={r.createdAt.slice(0, 10)}
          onClick={() => ph.navigate?.toTask(r.id)}
        />
      ))}
    </Section>
  );
}

// Inbox / to-dos: there's no data source for these yet, so this is a stub. The
// assignee toggle and "New" button are placeholders the host will wire up later.
function InboxSection() {
  const [scope, setScope] = useState<"me" | "team">("me");
  const accent = "#1d4aff";
  return (
    <Section title="Inbox" accent={accent} onNew={() => {}} loading={false} done={true} onLoadMore={() => {}} newDisabled={true} newTooltip="Coming soon">
      <div style={{ display: "flex", gap: 6, padding: "2px 2px 10px" }}>
        {(["me", "team"] as const).map((s) => {
          const active = scope === s;
          return (
            <button
              key={s}
              type="button"
              className="ph-btn"
              onClick={() => setScope(s)}
              style={{
                fontSize: 12,
                fontWeight: 500,
                padding: "4px 10px",
                borderRadius: 8,
                border: "1px solid " + (active ? accent : "var(--btn-border)"),
                background: active ? accent + "14" : "var(--btn-bg)",
                color: active ? accent : "var(--btn-color)",
                cursor: "pointer",
              }}
            >
              {s === "me" ? "Assigned to me" : "Teammates"}
            </button>
          );
        })}
      </div>
      <Empty label={"No " + (scope === "me" ? "items assigned to you" : "teammate items") + " yet."} />
    </Section>
  );
}

// Colors are CSS variables so the canvas follows the user's PostHog theme. The
// iframe loader toggles a \`dark\` class on <html> (sandboxRuntime.applyTheme);
// \`html.dark\` overrides win on specificity, so every value flips with no JS.
const STYLE_TEXT =
  ":root{" +
  "--bg-from:#f4f5f0;--bg-to:#eceee8;--card-bg:#ffffff;--card-border:#e4e5de;" +
  "--header-border:#eceee8;--title:#0d0d0d;--btn-border:#d8dbd1;--btn-bg:#f2f3ee;" +
  "--btn-color:#3a4036;--btn-hover-bg:#eceee8;--btn-hover-border:#cbd0c3;" +
  "--row-color:#3a4036;--row-hover-bg:#f2f3ee;--meta:#93998a;--empty:#a9af9f;" +
  "--page-color:#3a4036;--scroll-thumb:#cbd0c3;--scroll-thumb-hover:#a9af9f}" +
  "html.dark{" +
  "--bg-from:#1b1d1a;--bg-to:#141613;--card-bg:#202220;--card-border:#33362e;" +
  "--header-border:#2b2e27;--title:#f3f4ef;--btn-border:#3a3e34;--btn-bg:#2a2d26;" +
  "--btn-color:#d4d7cd;--btn-hover-bg:#34372f;--btn-hover-border:#474c3f;" +
  "--row-color:#d4d7cd;--row-hover-bg:#2a2d26;--meta:#8a917e;--empty:#6f7567;" +
  "--page-color:#d4d7cd;--scroll-thumb:#3a3e34;--scroll-thumb-hover:#4a4f42}" +
  ".ph-btn{transition:background .15s ease,border-color .15s ease,color .15s ease}" +
  ".ph-btn:hover{background:var(--btn-hover-bg);border-color:var(--btn-hover-border)}" +
  ".ph-row{transition:background .12s ease}" +
  ".ph-row:hover{background:var(--row-hover-bg)}" +
  "*::-webkit-scrollbar{width:10px;height:10px}" +
  "*::-webkit-scrollbar-thumb{background:var(--scroll-thumb);border-radius:8px;border:2px solid transparent;background-clip:padding-box}" +
  "*::-webkit-scrollbar-thumb:hover{background:var(--scroll-thumb-hover);background-clip:padding-box}";

export default function ChannelHome() {
  return (
    <div
      style={{
        minHeight: "100vh",
        boxSizing: "border-box",
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        padding: 40,
        background:
          "linear-gradient(180deg, var(--bg-from) 0%, var(--bg-to) 100%)",
        fontFamily:
          '"Open Runde", -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif',
        color: "var(--page-color)",
      }}
    >
      <style>{STYLE_TEXT}</style>
      <div
        style={{
          display: "flex",
          alignItems: "stretch",
          justifyContent: "center",
          gap: 20,
          width: "100%",
          maxWidth: 1200,
          flexWrap: "wrap",
        }}
      >
        <CanvasesSection />
        <InboxSection />
        <TasksSection />
      </div>
    </div>
  );
}
`;
}
