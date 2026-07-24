import type { AuthService } from "@posthog/core/auth/auth";
import { AUTH_SERVICE } from "@posthog/core/auth/auth.module";
import { inject, injectable } from "inversify";
import type {
  DashboardFileMeta,
  DashboardRecord,
  DashboardSummary,
} from "./dashboardSchemas";
import {
  DESKTOP_FS_CLIENT,
  type DesktopFsClient,
  type FsEntryBase,
} from "./desktopFsClient";
import { FREEFORM_TEMPLATE_ID, type FreeformVersion } from "./freeformSchemas";
import { fetchCurrentUser } from "./posthogApi";

// Desktop file-system "type" tag for a dashboard entry. Channels are `folder`
// rows (depth 1); dashboards are these `dashboard` files nested beneath them.
const DASHBOARD_TYPE = "dashboard";

// Display name (canvas h1) of a channel's auto-created home canvas.
const HOME_CANVAS_NAME = "Home";

// Dashboard-specific shape on top of the shared FS row. Our payload rides in
// `meta` — see DashboardFileMeta for what that blob holds.
interface FsEntry extends FsEntryBase {
  meta?: DashboardFileMeta | null;
  // The backend's creator user (standard PostHog UserBasic shape). Absent on
  // rows the API returns without an expanded creator.
  created_by?: {
    first_name?: string | null;
    last_name?: string | null;
    email?: string | null;
  } | null;
}

/**
 * Dashboards backed by the PostHog desktop file system (not local files), so a
 * dashboard is a `dashboard`-typed row nested under its channel folder and its
 * name is the last path segment — i.e. the canvas title. The freeform React
 * source lives in the row's `meta.code`. This keeps dashboards (and their names)
 * in sync with the backend, the same surface that owns channel names.
 */
@injectable()
export class DashboardsService {
  // The current user's display label, fetched once and reused (the creator is
  // the same user for the app's lifetime). `undefined` = not fetched yet;
  // `null` = fetched but unavailable (don't refetch on every create).
  private userLabel: string | null | undefined;

  constructor(
    @inject(DESKTOP_FS_CLIENT)
    private readonly fs: DesktopFsClient,
    @inject(AUTH_SERVICE)
    private readonly authService: AuthService,
  ) {}

  // The signed-in user's display name (or email), for stamping `created by` onto
  // canvases. Cached after the first lookup; never throws (returns undefined).
  private async currentUserLabel(): Promise<string | undefined> {
    if (this.userLabel !== undefined) return this.userLabel ?? undefined;
    const user = await fetchCurrentUser(this.authService);
    this.userLabel = user?.label ?? null;
    return this.userLabel ?? undefined;
  }

  private getEntry(id: string): Promise<FsEntry | null> {
    return this.fs.getEntry<FsEntry>(id, "dashboard");
  }

  async list(channelId: string): Promise<DashboardSummary[]> {
    // Fetch only this channel's dashboards via a server-side filter
    // (`parent=<channelPath>&type=dashboard`) rather than walking the whole
    // project file system and filtering client-side. Dashboards are created as
    // direct children of the channel folder, so the parent filter matches them.
    const channelPath = await this.channelPath(channelId);
    const entries = await this.fs.listByQuery<FsEntry>(
      `parent=${encodeURIComponent(channelPath)}&type=${DASHBOARD_TYPE}`,
      "dashboards",
    );
    return entries
      .map((e) => toRecord(e))
      .sort((a, b) => b.updatedAt - a.updatedAt)
      .map(
        ({
          id,
          channelId: cid,
          name,
          templateId,
          createdBy,
          updatedAt,
          code,
          generationTaskId,
          pinnedAt,
        }) => ({
          id,
          channelId: cid,
          name,
          templateId,
          createdBy,
          updatedAt,
          code,
          generationTaskId,
          pinnedAt,
        }),
      );
  }

  async get(id: string): Promise<DashboardRecord | null> {
    const entry = await this.getEntry(id);
    return entry ? toRecord(entry) : null;
  }

  async create(input: {
    channelId: string;
    name: string;
    templateId?: string;
  }): Promise<DashboardRecord> {
    const channelPath = await this.channelPath(input.channelId);
    const now = Date.now();
    const templateId = input.templateId ?? "freeform";
    const meta: DashboardFileMeta = {
      channelId: input.channelId,
      templateId,
      createdBy: await this.currentUserLabel(),
      createdAt: now,
      updatedAt: now,
    };
    const res = await this.fs.fetch("", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        path: `${channelPath}/${sanitizeSegment(input.name)}`,
        type: DASHBOARD_TYPE,
        meta,
      }),
    });
    if (!res.ok) throw new Error(`Failed to create dashboard (${res.status})`);
    return toRecord((await res.json()) as FsEntry);
  }

  // Persist a freeform canvas's source + edit history.
  async saveFreeform(input: {
    id: string;
    name?: string;
    code: string;
    versions: FreeformVersion[];
    currentVersionId?: string;
    context?: string;
  }): Promise<DashboardRecord> {
    const entry = await this.getEntry(input.id);
    const now = Date.now();
    const prevMeta = entry?.meta ?? {};
    const meta: DashboardFileMeta = {
      ...prevMeta,
      code: input.code,
      versions: input.versions,
      currentVersionId: input.currentVersionId,
      context: input.context,
      updatedAt: now,
      createdAt: prevMeta.createdAt ?? toEpoch(entry?.created_at),
    };

    const body: Record<string, unknown> = { meta };
    if (input.name && entry) {
      const parent = parentPath(entry.path);
      const next = sanitizeSegment(input.name);
      const newPath = parent ? `${parent}/${next}` : next;
      if (newPath !== entry.path) body.path = newPath;
    }

    const res = await this.fs.fetch(`${encodeURIComponent(input.id)}/`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    if (!res.ok) throw new Error(`Failed to save canvas (${res.status})`);
    return toRecord((await res.json()) as FsEntry);
  }

  // Record (or clear, when taskId is null) the task currently generating this
  // canvas. Merges into meta like the other writers so it never clobbers
  // code/versions; the agent's MCP publish likewise merges, so the two coexist.
  async setGenerationTask(input: {
    id: string;
    taskId: string | null;
  }): Promise<DashboardRecord> {
    const entry = await this.getEntry(input.id);
    const prevMeta = entry?.meta ?? {};
    const meta: DashboardFileMeta = {
      ...prevMeta,
      generationTaskId: input.taskId,
    };
    const res = await this.fs.fetch(`${encodeURIComponent(input.id)}/`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ meta }),
    });
    if (!res.ok) {
      throw new Error(`Failed to set generation task (${res.status})`);
    }
    return toRecord((await res.json()) as FsEntry);
  }

  // Pin (or unpin) a canvas to its channel. Writes `pinnedAt` into the row's
  // meta — shared across users — merging like the other writers so it never
  // clobbers code/versions. Unpinning drops the key (the PATCH sends the merged
  // meta sans pinnedAt, which the backend stores verbatim).
  async setPinned(input: {
    id: string;
    pinned: boolean;
  }): Promise<DashboardRecord> {
    const entry = await this.getEntry(input.id);
    const prevMeta = entry?.meta ?? {};
    const meta: DashboardFileMeta = {
      ...prevMeta,
      pinnedAt: input.pinned ? Date.now() : undefined,
    };
    const res = await this.fs.fetch(`${encodeURIComponent(input.id)}/`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ meta }),
    });
    if (!res.ok) throw new Error(`Failed to set pin (${res.status})`);
    return toRecord((await res.json()) as FsEntry);
  }

  // Rename a canvas by rewriting the last path segment (the title). Touches only
  // the path, leaving meta (code/versions/etc.) intact — used to auto-name a
  // freshly-created canvas from its generation prompt.
  async rename(input: { id: string; name: string }): Promise<DashboardRecord> {
    const entry = await this.getEntry(input.id);
    if (!entry) throw new Error("Dashboard not found");
    const parent = parentPath(entry.path);
    const next = sanitizeSegment(input.name);
    const newPath = parent ? `${parent}/${next}` : next;
    if (newPath === entry.path) return toRecord(entry);
    const res = await this.fs.fetch(`${encodeURIComponent(input.id)}/`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ path: newPath }),
    });
    if (!res.ok) throw new Error(`Failed to rename canvas (${res.status})`);
    return toRecord((await res.json()) as FsEntry);
  }

  // Ensure the channel has a home canvas: the freeform board shown when the
  // channel name is clicked. Idempotent — if the channel folder's meta already
  // points at a live canvas, return it; otherwise create one, seed its source,
  // and record its id on the folder. Safe to call on channel create and lazily
  // on first open (backfills channels made before home canvases existed).
  async ensureHomeCanvas(channelId: string): Promise<DashboardRecord> {
    const folder = await this.getEntry(channelId);
    if (!folder) throw new Error("Channel not found");

    // Resolve (or create) the canvas, then seed it. Each step is recorded before
    // the next runs, so a failure mid-way leaves a retryable state rather than an
    // orphan: if `create` succeeds but seeding throws, the folder already points
    // at the canvas, so the next call reuses it (and seeds it below) instead of
    // creating a second "Home".
    const existingId = folder.meta?.homeCanvasId;
    let record = existingId ? await this.get(existingId) : null;
    if (!record) {
      // The canvas's own id is baked into the code so it can exclude itself from
      // the "Canvases" list; the channel id lets it resolve the (rename-safe)
      // folder path at runtime.
      record = await this.create({
        channelId,
        name: HOME_CANVAS_NAME,
        templateId: FREEFORM_TEMPLATE_ID,
      });
      await this.setHomeCanvasId(channelId, record.id, folder);
    }

    // Seed the source if it isn't already (covers a prior create whose seed
    // failed). A canvas that already has code is returned untouched.
    if (!record.code) {
      const code = buildHomeCanvasCode(channelId, record.id);
      const version: FreeformVersion = {
        id: `home-${record.id}`,
        code,
        createdAt: Date.now(),
      };
      record = await this.saveFreeform({
        id: record.id,
        code,
        versions: [version],
        currentVersionId: version.id,
      });
    }
    return record;
  }

  // Rebuild a channel's home canvas from the default template, discarding edits.
  // Non-destructive: the pre-reset source is kept as the prior version (so Undo
  // restores it) and the regenerated default is appended as the new head. If the
  // channel has no home canvas yet, this is just a create. Only valid for the
  // home canvas — regular canvases have no "default" to reset to.
  async resetHomeCanvas(channelId: string): Promise<DashboardRecord> {
    const folder = await this.getEntry(channelId);
    if (!folder) throw new Error("Channel not found");

    const homeCanvasId = folder.meta?.homeCanvasId;
    if (!homeCanvasId) return this.ensureHomeCanvas(channelId);
    const record = await this.get(homeCanvasId);
    if (!record) return this.ensureHomeCanvas(channelId);

    const code = buildHomeCanvasCode(channelId, homeCanvasId);
    const version: FreeformVersion = {
      id: `reset-${homeCanvasId}-${Date.now()}`,
      code,
      createdAt: Date.now(),
    };
    return this.saveFreeform({
      id: homeCanvasId,
      code,
      versions: [...(record.versions ?? []), version],
      currentVersionId: version.id,
    });
  }

  // Point a channel folder at its home canvas by writing homeCanvasId onto the
  // folder's meta (preserving any existing meta keys).
  private async setHomeCanvasId(
    channelId: string,
    homeCanvasId: string,
    folder?: FsEntry | null,
  ): Promise<void> {
    const entry = folder ?? (await this.getEntry(channelId));
    const prevMeta = entry?.meta ?? {};
    const meta: DashboardFileMeta = { ...prevMeta, homeCanvasId };
    const res = await this.fs.fetch(`${encodeURIComponent(channelId)}/`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ meta }),
    });
    if (!res.ok) {
      throw new Error(`Failed to set channel home canvas (${res.status})`);
    }
  }

  async delete(id: string): Promise<void> {
    const res = await this.fs.fetch(`${encodeURIComponent(id)}/`, {
      method: "DELETE",
    });
    // Already gone is a successful delete; surface anything else.
    if (!res.ok && res.status !== 404) {
      throw new Error(`Failed to delete dashboard (${res.status})`);
    }
  }

  // Resolve a channel's folder path from its file-system id so child dashboards
  // can be created beneath it (paths are name-based, ids are not).
  private async channelPath(channelId: string): Promise<string> {
    const entry = await this.getEntry(channelId);
    if (!entry) throw new Error("Channel not found");
    return entry.path;
  }
}

// The seeded React source for a channel's home canvas. It runs in the freeform
// sandbox (null-origin iframe), so its only data avenue is `window.ph.query`
// (HogQL). It reads three lists from the `system.file_system` HogQL table:
//   - Canvases: this channel's `dashboard` rows (excluding the home canvas).
//   - Inbox / to-dos: stubbed (no data source yet) with an assignee filter.
//   - Tasks: this channel's filed `task` rows, newest first.
// Each list shows a page at a time and loads more as its own box is scrolled.
// Rows and the "New" buttons drive host routing via the allowlisted
// `ph.navigate` bridge (toTask/toNewTask/toCanvas/toNewCanvas); the Inbox stub
// stays a no-op until it has a data source. channelId is host-supplied, so the
// canvas can only navigate within its own channel.
// channelId is baked in (the path is resolved at runtime so renames are safe);
// homeCanvasId lets the Canvases list exclude this board.
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

function lastSegment(path: string): string {
  const i = path.lastIndexOf("/");
  return i === -1 ? path : path.slice(i + 1);
}

// Resolve the channel folder's current path from its stable id, so renaming the
// channel doesn't break the lists (the path, not the id, scopes child rows).
async function resolveChannelPath(): Promise<string> {
  const res = await ph.query(
    "SELECT path FROM system.file_system WHERE id = " + sql(CHANNEL_ID) + " LIMIT 1",
  );
  const rows = (res && res.results) || [];
  return rows.length ? String(rows[0][0]) : "";
}

type Row = { id: string; title: string; ref: string | null; createdAt: string };

// Paginated reader for the channel's filesystem rows of a given type, newest
// first. Resolves the channel path once, then walks pages by offset.
function useChannelRows(kind: "dashboard" | "task") {
  const [rows, setRows] = useState<Row[]>([]);
  const [loading, setLoading] = useState(false);
  const [done, setDone] = useState(false);
  const offsetRef = useRef(0);
  const pathRef = useRef<string | null>(null);
  const busyRef = useRef(false);

  const loadMore = useCallback(async () => {
    if (busyRef.current || done) return;
    busyRef.current = true;
    setLoading(true);
    try {
      if (pathRef.current === null) pathRef.current = await resolveChannelPath();
      const prefix = pathRef.current + "/";
      const exclude =
        kind === "dashboard" ? " AND id != " + sql(HOME_CANVAS_ID) : "";
      const query =
        "SELECT id, path, ref, created_at FROM system.file_system" +
        " WHERE type = " + sql(kind) +
        " AND surface = 'desktop'" +
        " AND startsWith(path, " + sql(prefix) + ")" +
        exclude +
        " ORDER BY created_at DESC LIMIT " + PAGE_SIZE +
        " OFFSET " + offsetRef.current;
      const res = await ph.query(query);
      const batch: Row[] = ((res && res.results) || []).map((r: any[]) => ({
        id: String(r[0]),
        title: lastSegment(String(r[1])),
        ref: r[2] == null ? null : String(r[2]),
        createdAt: String(r[3]),
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
          // A task row's file-system id is NOT the task id; the task id is the
          // row's ref (ChannelTasksService files it as ref=taskId). Only rows
          // with a ref are navigable.
          onClick={r.ref ? () => ph.navigate?.toTask(r.ref as string) : undefined}
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

// Build the renderer-facing record from a file-system row. The name is the last
// path segment (the canvas title); code + timestamps ride in `meta`.
function toRecord(entry: FsEntry): DashboardRecord {
  const meta = entry.meta ?? {};
  const createdAt = meta.createdAt ?? toEpoch(entry.created_at);
  return {
    id: entry.id,
    channelId: meta.channelId ?? "",
    name: lastSegment(entry.path),
    templateId: meta.templateId ?? "freeform",
    code: meta.code,
    versions: meta.versions,
    currentVersionId: meta.currentVersionId,
    context: meta.context,
    generationTaskId: meta.generationTaskId,
    // Prefer our stamped meta; fall back to the FS row's creator if present.
    createdBy: meta.createdBy ?? creatorName(entry.created_by),
    createdAt,
    updatedAt: meta.updatedAt ?? createdAt,
    pinnedAt: meta.pinnedAt,
  };
}

// Human-readable creator from the backend's `created_by` user: full name when
// present, else email, else undefined (we don't render an id).
function creatorName(createdBy?: FsEntry["created_by"]): string | undefined {
  if (!createdBy) return undefined;
  const name = [createdBy.first_name, createdBy.last_name]
    .filter(Boolean)
    .join(" ")
    .trim();
  return name || createdBy.email || undefined;
}

// Path segments are "/"-separated on the backend, so a name can't contain one.
function sanitizeSegment(name: string): string {
  const cleaned = name.replace(/\//g, " ").replace(/\s+/g, " ").trim();
  return cleaned || "Untitled dashboard";
}

function parentPath(path: string): string {
  const i = path.lastIndexOf("/");
  return i === -1 ? "" : path.slice(0, i);
}

function lastSegment(path: string): string {
  const i = path.lastIndexOf("/");
  return i === -1 ? path : path.slice(i + 1);
}

function toEpoch(iso?: string): number {
  if (!iso) return Date.now();
  const t = Date.parse(iso);
  return Number.isNaN(t) ? Date.now() : t;
}
