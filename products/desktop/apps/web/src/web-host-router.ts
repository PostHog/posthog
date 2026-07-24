import { TEAM_SKILLS_SERVICE } from "@posthog/core/skills/identifiers";
import type { TeamSkillsService } from "@posthog/core/skills/teamSkillsService";
import { resolveService } from "@posthog/di/container";
import { analyticsRouter } from "@posthog/host-router/routers/analytics.router";
import { authRouter } from "@posthog/host-router/routers/auth.router";
import { canvasDataRouter } from "@posthog/host-router/routers/canvas-data.router";
import { canvasTemplatesRouter } from "@posthog/host-router/routers/canvas-templates.router";
import { channelTasksRouter } from "@posthog/host-router/routers/channel-tasks.router";
import { cloudTaskRouter } from "@posthog/host-router/routers/cloud-task.router";
import { dashboardsRouter } from "@posthog/host-router/routers/dashboards.router";
import { publicProcedure, router } from "@posthog/host-trpc/trpc";
import {
  type CloudRegion,
  getCloudUrlFromRegion,
  tabsSnapshotSchema,
} from "@posthog/shared";
import { getAuthenticatedClient } from "@posthog/ui/features/auth/authClientImperative";
import { z } from "zod";
import { getWebPreviewConfigOptions } from "./web-agent-config";
import { webArchiveStore } from "./web-archive-store";
import {
  getWebAttachmentBase64,
  getWebAttachmentDataUrl,
  putWebAttachment,
} from "./web-attachment-store";
import { webBrowserTabsStore } from "./web-browser-tabs-store";
import { fetchS3Logs } from "./web-logs";
import { webTaskMetadataStore } from "./web-task-metadata-store";
import { webWorkspaceStore } from "./web-workspace-store";

// The in-browser slice of the host router. Electron serves the full hostRouter
// over IPC from its main process; the web host serves the subset the
// cloud-tasks-only surface needs, in the same JS context via localLink
// (web-trpc.ts). auth, cloudTask, and analytics are the REAL routers — their
// backing services (AuthService, CloudTaskService) are host-agnostic core code
// bound in web-container.ts. The rest are benign stubs for procedures the
// shared UI calls unconditionally on boot/mount. Anything not listed fails
// with NOT_FOUND at call time — same behavior as the HTTP dev stub this
// replaces, and a deliberate signal of where the web host is still thin.

// A subscription that stays open but never emits — the web host has no source
// for these host-push streams (idle kills, deep links). Held until the client
// aborts so the tRPC subscription doesn't error.
const neverEmit = publicProcedure.subscription(async function* (opts) {
  yield* [] as never[];
  await new Promise<void>((resolve) => {
    opts.signal?.addEventListener("abort", () => resolve(), { once: true });
  });
});

// Deep links are a desktop URL-scheme feature (posthog-code://); the browser has
// no equivalent, so every pending-link query resolves null and every open-*
// stream never emits. Stubbed to silence NOT_FOUND noise from __root's deep-link
// hooks, which poll these on mount.
const deepLinkStubRouter = router({
  getPendingDeepLink: publicProcedure.query(() => null),
  getPendingReportLink: publicProcedure.query(() => null),
  getPendingScoutLink: publicProcedure.query(() => null),
  getPendingNewTaskLink: publicProcedure.query(() => null),
  getPendingApprovalLink: publicProcedure.query(() => null),
  getPendingOpenTarget: publicProcedure.query(() => null),
  getPendingCanvasLink: publicProcedure.query(() => null),
  getPendingChannelLink: publicProcedure.query(() => null),
  onOpenTask: neverEmit,
  onOpenReport: neverEmit,
  onOpenScout: neverEmit,
  onNewTaskAction: neverEmit,
  onOpenApproval: neverEmit,
  onOpenTarget: neverEmit,
  onOpenCanvas: neverEmit,
  onOpenChannel: neverEmit,
});

// Slack/GitHub connect. Desktop opens the PostHog integration authorize URL in
// the system browser and relays the result back through a posthog-code:// deep
// link (captured by the main process). The browser has no URL scheme, but it
// doesn't need one: the third-party (Slack/GitHub) OAuth code exchange happens
// entirely server-side, so by the time the popup lands there is nothing to
// relay — the integration already exists in getIntegrations(). So startFlow just
// opens the same authorize URL in a new tab, and the connect hooks (useSlack/
// GitHubConnect) refetch the integrations list on window-focus while
// "connecting" — returning to the app surfaces the connection. connect_from is
// "posthog_web" (not "posthog_code") so PostHog doesn't try to bounce the popup
// through the desktop deep link. The callback procedures stay inert (there is no
// deep-link callback on web); the app-wide callback hooks consume the null / see
// streams that never emit, as before.
function openIntegrationAuthorize(
  region: string,
  projectId: number,
  kind: "slack" | "github",
): { success: boolean; error?: string } {
  const cloudUrl = getCloudUrlFromRegion(region as CloudRegion);
  const next = `/account-connected/${kind}-integration?provider=${kind}&project_id=${projectId}&connect_from=posthog_web`;
  const authorizeUrl = `${cloudUrl}/api/environments/${projectId}/integrations/authorize/?kind=${kind}&next=${encodeURIComponent(next)}`;
  const opened = window.open(authorizeUrl, "_blank", "noopener,noreferrer");
  return opened
    ? { success: true }
    : {
        success: false,
        error: `Enable pop-ups for this site to connect ${kind === "slack" ? "Slack" : "GitHub"}.`,
      };
}

const slackIntegrationRouter = router({
  consumePendingCallback: publicProcedure.query(() => null),
  onCallback: neverEmit,
  onFlowTimedOut: neverEmit,
  startFlow: publicProcedure
    .input(z.object({ region: z.string(), projectId: z.number() }))
    .mutation(({ input }) =>
      openIntegrationAuthorize(input.region, input.projectId, "slack"),
    ),
});

const githubIntegrationRouter = router({
  consumePendingCallback: publicProcedure.query(() => null),
  onCallback: neverEmit,
  onFlowTimedOut: neverEmit,
  startFlow: publicProcedure
    .input(z.object({ region: z.string(), projectId: z.number() }))
    .mutation(({ input }) =>
      openIntegrationAuthorize(input.region, input.projectId, "github"),
    ),
});

const agentStubRouter = router({
  // SessionService subscribes to this in its constructor. No local agent
  // sessions exist on web, so hold the stream open and never emit.
  onSessionIdleKilled: publicProcedure.subscription(async function* (opts) {
    yield* [] as { taskRunId: string }[];
    await new Promise<void>((resolve) => {
      opts.signal?.addEventListener("abort", () => resolve(), { once: true });
    });
  }),
  // Called by resetSessionService() on logout/project switch.
  resetAll: publicProcedure.mutation(() => undefined),
  // Model/mode/effort options for the task-input preview + cloud run creation
  // (a cloud run requires a model). Real: fetched from the CORS-open PostHog LLM
  // gateway, same logic the desktop main process runs (see web-agent-config.ts).
  getPreviewConfigOptions: publicProcedure
    .input(
      z.object({
        apiHost: z.string(),
        adapter: z.enum(["claude", "codex"]).default("claude"),
      }),
    )
    .query(({ input }) =>
      getWebPreviewConfigOptions(input.apiHost, input.adapter),
    ),
});

const osStubRouter = router({
  openExternal: publicProcedure
    .input(z.object({ url: z.string() }))
    .mutation(({ input }) => {
      window.open(input.url, "_blank", "noopener,noreferrer");
    }),
  // Composer attachments. On desktop these write the browser-picked bytes to a
  // local temp file and return its path (which becomes the attachment id, later
  // read back for cloud upload). On web there's no filesystem, so stash the
  // already-base64'd bytes in an in-memory store under a synthetic id — the
  // upload pipeline reads them back via CLOUD_ARTIFACT_READ_FILE_AS_BASE64.
  saveClipboardImage: publicProcedure
    .input(
      z.object({
        base64Data: z.string(),
        mimeType: z.string(),
        originalName: z.string().optional(),
      }),
    )
    .mutation(({ input }) => {
      const { path, name, mimeType } = putWebAttachment({
        base64Data: input.base64Data,
        name: input.originalName ?? "image",
        mimeType: input.mimeType,
      });
      return { path, name, mimeType: mimeType ?? input.mimeType };
    }),
  saveClipboardFile: publicProcedure
    .input(
      z.object({
        base64Data: z.string(),
        originalName: z.string().optional(),
      }),
    )
    .mutation(({ input }) =>
      putWebAttachment({
        base64Data: input.base64Data,
        name: input.originalName ?? "attachment",
      }),
    ),
  saveClipboardText: publicProcedure
    .input(z.object({ text: z.string(), originalName: z.string().optional() }))
    .mutation(({ input }) =>
      putWebAttachment({
        base64Data: btoa(unescape(encodeURIComponent(input.text))),
        name: input.originalName ?? "pasted-text.txt",
      }),
    ),
  // Image downscaling is a desktop optimization over a local file; on web the
  // "filePath" is already our synthetic id, so pass it through unchanged.
  downscaleImageFile: publicProcedure
    .input(z.object({ filePath: z.string() }))
    .mutation(({ input }) => ({ path: input.filePath, name: "image" })),
  // The composer image preview reads an attachment by id (our synthetic path)
  // and expects a data URL. Build it from the stored bytes + mime type.
  readFileAsDataUrl: publicProcedure
    .input(
      z.object({
        filePath: z.string(),
        maxSizeBytes: z.number().optional(),
      }),
    )
    .query(({ input }) => getWebAttachmentDataUrl(input.filePath)),
});

// Attachment bytes read back for cloud upload. Desktop reads a real temp file
// via Node fs; on web the "filePath" is our synthetic attachment id, resolved to
// the in-memory bytes. CloudArtifactService (via sessionServiceHost) reads
// attachments through fs.readFileAsBase64 at task-submit time.
const fsStubRouter = router({
  readFileAsBase64: publicProcedure
    .input(z.object({ filePath: z.string() }))
    .query(({ input }) => getWebAttachmentBase64(input.filePath)),
});

const skillsStubRouter = router({
  // Backs the composer's "/" skill menu and typed /skill-command resolution.
  // No local skills dir on web, so surface the team's cloud skills instead
  // (tagged source "user" — where a team skill lands when installed — with the
  // skill name as a synthetic path the web bundler resolves by name). When a
  // skill is used, web-skill-bundler fetches + zips its content for the run.
  list: publicProcedure.query(async () => {
    const client = await getAuthenticatedClient();
    if (!client) return [];
    const service = resolveService<TeamSkillsService>(TEAM_SKILLS_SERVICE);
    const listing = await service.listTeamSkills(client);
    return listing.skills.map((skill) => ({
      name: skill.name,
      description: skill.description,
      source: "user" as const,
      path: skill.name,
      editable: false,
      skillMdBytes: 0,
    }));
  }),
});

const additionalDirectoriesStubRouter = router({
  // Queried on task-input mount; only meaningful for local workspaces.
  listDefaults: publicProcedure.query(() => []),
});

const foldersStubRouter = router({
  // Queried on task-input mount to prefill a local repo path.
  getMostRecentlyAccessedRepository: publicProcedure.query(() => null),
  // Called by getTaskDirectory during task creation to resolve a local repo
  // folder from a git remote. No local repos on web, so there's no directory —
  // getTaskDirectory returns null and the cloud path proceeds without one.
  getRepositoryByRemoteUrl: publicProcedure
    .input(z.object({ remoteUrl: z.string() }))
    .query(() => null),
});

const workspaceStubRouter = router({
  // useWorkspaces() at __root maps taskId -> workspace. The sidebar's default
  // view derives its task list from this map (computeSummaryIds), so cloud
  // tasks created in this browser are tracked in a localStorage-backed store
  // and returned here — otherwise a created task never appears in the sidebar.
  getAll: publicProcedure.query(() => webWorkspaceStore.getAll()),
  // Fired by __root's cloud-workspace reconcile effect (gated behind the
  // sync-cloud-tasks flag). Register a cloud entry for each task so a boot-time
  // reconcile seeds the sidebar; report them all as created.
  reconcileCloudWorkspaces: publicProcedure
    .input(z.object({ taskIds: z.array(z.string()) }))
    .mutation(({ input }) => {
      const created: string[] = [];
      const archivedIds = new Set(webArchiveStore.ids());
      for (const taskId of input.taskIds) {
        // Don't resurrect a workspace entry for a task the user archived here.
        if (archivedIds.has(taskId)) continue;
        if (!webWorkspaceStore.getAll()[taskId]) {
          webWorkspaceStore.addCloud(taskId, null, new Date().toISOString());
          created.push(taskId);
        }
      }
      return { created };
    }),
  // Task-creation saga's "cloud_workspace_creation" step. Register the cloud
  // workspace so it survives the invalidate+refetch that follows creation (the
  // saga builds its own literal for the optimistic cache; this persists it). The
  // saga discards the return value.
  create: publicProcedure
    .input(
      z
        .object({ taskId: z.string(), branch: z.string().optional() })
        .passthrough(),
    )
    .mutation(({ input }) => {
      webWorkspaceStore.addCloud(
        input.taskId,
        input.branch ?? null,
        new Date().toISOString(),
      );
      return { worktree: null, linkedBranch: null };
    }),
  // Compensating rollback for the step above if a later step fails.
  delete: publicProcedure
    .input(z.object({ taskId: z.string() }).passthrough())
    .mutation(({ input }) => {
      webWorkspaceStore.remove(input.taskId);
    }),

  // ── Per-device task metadata (pins + viewed/activity timestamps) ──
  // Desktop persists these in a local metadata service. The sidebar and the
  // archive flow read them (archive awaits getPinnedTaskIds + unpin early, so a
  // missing procedure rejects the whole archive). Backed by localStorage.
  togglePin: publicProcedure
    .input(z.object({ taskId: z.string() }))
    .mutation(({ input }) => webTaskMetadataStore.togglePin(input.taskId)),
  markViewed: publicProcedure
    .input(z.object({ taskId: z.string() }))
    .mutation(({ input }) => {
      webTaskMetadataStore.markViewed(input.taskId);
    }),
  markActivity: publicProcedure
    .input(z.object({ taskId: z.string() }))
    .mutation(({ input }) => {
      webTaskMetadataStore.markActivity(input.taskId);
    }),
  getPinnedTaskIds: publicProcedure.query(() =>
    webTaskMetadataStore.getPinnedTaskIds(),
  ),
  getTaskTimestamps: publicProcedure
    .input(z.object({ taskId: z.string() }))
    .query(({ input }) => webTaskMetadataStore.get(input.taskId)),
  getAllTaskTimestamps: publicProcedure.query(() =>
    webTaskMetadataStore.getAll(),
  ),
});

// Archiving on the web host is a per-device "hide from my sidebar" flag (there
// is no local worktree to trash). Backed by localStorage; archiving also drops
// the workspace entry so the task leaves the sidebar's task list.
const archiveStubRouter = router({
  archive: publicProcedure
    .input(z.object({ taskId: z.string() }))
    .mutation(({ input }) => {
      const entry = webArchiveStore.add(input.taskId, new Date().toISOString());
      webWorkspaceStore.remove(input.taskId);
      return entry;
    }),
  unarchive: publicProcedure
    .input(
      z.object({ taskId: z.string(), recreateBranch: z.boolean().optional() }),
    )
    .mutation(({ input }) => {
      webArchiveStore.remove(input.taskId);
      // Re-register a cloud workspace so the task returns to the sidebar.
      webWorkspaceStore.addCloud(input.taskId, null, new Date().toISOString());
      return { taskId: input.taskId, worktreeName: null };
    }),
  list: publicProcedure.query(() => webArchiveStore.list()),
  archivedTaskIds: publicProcedure.query(() => webArchiveStore.ids()),
  delete: publicProcedure
    .input(z.object({ taskId: z.string() }))
    .mutation(({ input }) => {
      webArchiveStore.remove(input.taskId);
      webWorkspaceStore.remove(input.taskId);
    }),
});

// Cloud task log history. fetchS3Logs is a real, portable fetch of the
// backend's pre-signed log_url (see web-logs.ts); the local-cache reads/writes
// are no-ops since the browser has no durable per-run log cache. This is what
// hydrates a cloud task's transcript on open/reconnect and fills SSE gaps.
const logsStubRouter = router({
  fetchS3Logs: publicProcedure
    .input(z.object({ logUrl: z.string().min(1) }))
    .query(({ input }) => fetchS3Logs(input.logUrl)),
  readLocalLogs: publicProcedure
    .input(z.object({ taskRunId: z.string() }))
    .query(() => null),
  readLocalLogsCollapsed: publicProcedure
    .input(z.object({ taskRunId: z.string() }))
    .query(() => null),
  readLocalLogsTail: publicProcedure
    .input(z.object({ taskRunId: z.string(), maxBytes: z.number() }))
    .query(() => null),
  writeLocalLogs: publicProcedure
    .input(z.object({ taskRunId: z.string(), content: z.string() }))
    .mutation(() => undefined),
});

// Channels browser-tab strip. Desktop backs this with a SQLite-owned service in
// the Electron main process; web forwards to a localStorage-backed store that
// runs the SAME shared pure transforms (see web-browser-tabs-store.ts). This is
// a REAL implementation, not a stub — the "+" (new tab), close, reorder, and
// in-tab navigation all persist and fan out to the renderer mirror via
// onSnapshotChange, exactly as on desktop (with a single window).
const tabTargetFields = {
  dashboardId: z.string().nullable().default(null),
  taskId: z.string().nullable().default(null),
  channelId: z.string().nullable().default(null),
  channelSection: z.string().nullable().default(null),
  appView: z.string().nullable().default(null),
};
const browserTabsRouter = router({
  getSnapshot: publicProcedure
    .output(tabsSnapshotSchema)
    .query(() => webBrowserTabsStore.getSnapshot()),
  getPrimaryWindowId: publicProcedure
    .output(z.string())
    .query(() => webBrowserTabsStore.getPrimaryWindowId()),
  openOrFocus: publicProcedure
    .input(
      z.object({
        windowId: z.string(),
        ...tabTargetFields,
        tabId: z.string().optional(),
      }),
    )
    .output(tabsSnapshotSchema)
    .mutation(({ input }) => webBrowserTabsStore.openOrFocus(input)),
  newBlankTab: publicProcedure
    .input(z.object({ windowId: z.string(), tabId: z.string().optional() }))
    .output(tabsSnapshotSchema)
    .mutation(({ input }) => webBrowserTabsStore.newBlankTab(input)),
  setTabTarget: publicProcedure
    .input(z.object({ tabId: z.string(), ...tabTargetFields }))
    .output(tabsSnapshotSchema)
    .mutation(({ input }) => webBrowserTabsStore.setTabTarget(input)),
  close: publicProcedure
    .input(z.object({ tabId: z.string() }))
    .output(tabsSnapshotSchema)
    .mutation(({ input }) => webBrowserTabsStore.close(input.tabId)),
  closeMany: publicProcedure
    .input(
      z.object({
        tabIds: z.array(z.string()),
        focusTabId: z.string().nullable().default(null),
      }),
    )
    .output(tabsSnapshotSchema)
    .mutation(({ input }) =>
      webBrowserTabsStore.closeMany(input.tabIds, input.focusTabId),
    ),
  setOrder: publicProcedure
    .input(z.object({ windowId: z.string(), tabIds: z.array(z.string()) }))
    .output(tabsSnapshotSchema)
    .mutation(({ input }) => webBrowserTabsStore.setOrder(input)),
  setActiveTab: publicProcedure
    .input(z.object({ windowId: z.string(), tabId: z.string().nullable() }))
    .output(tabsSnapshotSchema)
    .mutation(({ input }) => webBrowserTabsStore.setActiveTab(input)),
  onSnapshotChange: publicProcedure.subscription(async function* (opts) {
    for await (const snapshot of webBrowserTabsStore.snapshotChangeEvents(
      opts.signal ?? undefined,
    )) {
      yield snapshot;
    }
  }),
});

export const webHostRouter = router({
  additionalDirectories: additionalDirectoriesStubRouter,
  agent: agentStubRouter,
  analytics: analyticsRouter,
  archive: archiveStubRouter,
  auth: authRouter,
  browserTabs: browserTabsRouter,
  // Canvas / Channels: real host-router routers over the host-agnostic canvas
  // core services (bound via canvasCoreModule in web-container), which reach the
  // PostHog desktop_file_system API through authenticatedFetch — no Node backend.
  canvasData: canvasDataRouter,
  canvasTemplates: canvasTemplatesRouter,
  channelTasks: channelTasksRouter,
  cloudTask: cloudTaskRouter,
  dashboards: dashboardsRouter,
  deepLink: deepLinkStubRouter,
  folders: foldersStubRouter,
  fs: fsStubRouter,
  githubIntegration: githubIntegrationRouter,
  logs: logsStubRouter,
  os: osStubRouter,
  skills: skillsStubRouter,
  slackIntegration: slackIntegrationRouter,
  workspace: workspaceStubRouter,
});

export type WebHostRouter = typeof webHostRouter;
