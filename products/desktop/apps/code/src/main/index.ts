import "reflect-metadata";
import os from "node:os";
import { TypedEventEmitter } from "@posthog/shared";
import type { WorkspaceClient } from "@posthog/workspace-client/client";
import { createReconnectingWorkspaceClient } from "@posthog/workspace-client/client";
import type { FileWatcherEvent } from "@posthog/workspace-client/types";
import { app, BrowserWindow, dialog, session } from "electron";
import log from "electron-log/main";
import "./utils/logger";
import "./services/index.js";
import type { AuthService } from "@posthog/core/auth/auth";
import { focusHostModule } from "@posthog/core/focus/focus-host.module";
import {
  FOCUS_SESSION_STORE,
  FOCUS_WORKSPACE_CLIENT,
  FOCUS_WORKTREE_PATHS,
} from "@posthog/core/focus/host-focus";
import { GIT_WORKSPACE_CLIENT } from "@posthog/core/git/identifiers";
import type { GitHubIntegrationService } from "@posthog/core/integrations/github";
import {
  GITHUB_INTEGRATION_SERVICE,
  SLACK_INTEGRATION_SERVICE,
} from "@posthog/core/integrations/identifiers";
import type { SlackIntegrationService } from "@posthog/core/integrations/slack";
import type { ApprovalLinkService } from "@posthog/core/links/approval-link";
import type { CanvasLinkService } from "@posthog/core/links/canvas-link";
import type { ChannelLinkService } from "@posthog/core/links/channel-link";
import type { InboxLinkService } from "@posthog/core/links/inbox-link";
import type { NewTaskLinkService } from "@posthog/core/links/new-task-link";
import type { ScoutLinkService } from "@posthog/core/links/scout-link";
import type { TaskLinkService } from "@posthog/core/links/task-link";
import { NOTIFICATION_SERVICE } from "@posthog/core/notification/identifiers";
import type { NotificationService } from "@posthog/core/notification/notification";
import { OAUTH_SERVICE } from "@posthog/core/oauth/identifiers";
import type { OAuthService } from "@posthog/core/oauth/oauth";
import type { UpdatesService } from "@posthog/core/updates/updates";
import { CONNECTIVITY_CLIENT } from "@posthog/host-router/ports/connectivity-client";
import { ENVIRONMENT_CLIENT } from "@posthog/host-router/ports/environment-client";
import { FILE_WATCHER_CONTROL } from "@posthog/host-router/ports/file-watcher-control";
import { ANALYTICS_EVENTS } from "@posthog/shared/analytics-events";
import type { DatabaseService } from "@posthog/workspace-server/db/service";
import type { ExternalAppsService } from "@posthog/workspace-server/services/external-apps/external-apps";
import {
  FS_SERVICE,
  type FsCapability,
} from "@posthog/workspace-server/services/fs/identifiers";
import type { PosthogPluginService } from "@posthog/workspace-server/services/posthog-plugin/posthog-plugin";
import { SUSPENSION_SERVICE } from "@posthog/workspace-server/services/suspension/identifiers";
import type { SuspensionService } from "@posthog/workspace-server/services/suspension/suspension";
import type { WorkspaceService } from "@posthog/workspace-server/services/workspace/workspace";
import { initializeDeepLinks, registerDeepLinkHandlers } from "./deep-links";
import { container } from "./di/container";
import {
  APP_LIFECYCLE_SERVICE,
  APPROVAL_LINK_SERVICE,
  AUTH_SERVICE,
  CANVAS_LINK_SERVICE,
  CHANNEL_LINK_SERVICE,
  DATABASE_SERVICE,
  DEV_NETWORK_SERVICE,
  DISCORD_PRESENCE_SERVICE,
  EXTERNAL_APPS_SERVICE,
  FILE_WATCHER_SERVICE,
  INBOX_LINK_SERVICE,
  FS_SERVICE as MAIN_FS_SERVICE,
  NEW_TASK_LINK_SERVICE,
  POSTHOG_PLUGIN_SERVICE,
  SCOUT_LINK_SERVICE,
  TASK_LINK_SERVICE,
  UPDATES_SERVICE,
  WORKSPACE_CLIENT,
  WORKSPACE_SERVER_SERVICE,
  WORKSPACE_SERVICE,
} from "./di/tokens";
import { setupExternalLinkPermissionHandlers } from "./external-links";
import { posthogNodeAnalytics } from "./platform-adapters/posthog-analytics";
import { registerMcpSandboxProtocol } from "./protocols/mcp-sandbox";
import type { AppLifecycleService } from "./services/app-lifecycle/service";
import type { DevNetworkService } from "./services/dev-network/service";
import { initDevToolbar } from "./services/dev-toolbar";
import type { DiscordPresenceService } from "./services/discord-presence/service";
import {
  focusSessionStore,
  focusWorktreePaths,
} from "./services/focus/desktop-adapters";
import {
  WorkspaceServerEvent,
  type WorkspaceServerService,
  WorkspaceServerStatus,
} from "./services/workspace-server/service";
import {
  collectMemorySnapshot,
  flattenMemorySnapshot,
} from "./utils/crash-diagnostics";
import { ensureClaudeConfigDir } from "./utils/env";
import {
  getChromiumLogFilePath,
  getLogFilePath,
  getNetworkLogFilePath,
  readChromiumLogTail,
} from "./utils/logger";
import { isMacosPackagedUnsafeBundleLocation } from "./utils/macos-packaged-install-guard";
import { installMainFetchLogging } from "./utils/network-fetch-logger";
import { installRendererNetworkLogging } from "./utils/network-webrequest-logger";
import { createWindow } from "./window";

type FileWatcherEventsByKind = {
  [K in FileWatcherEvent["kind"]]: Extract<FileWatcherEvent, { kind: K }>;
};

export class FileWatcherBridge extends TypedEventEmitter<FileWatcherEventsByKind> {
  private subs = new Map<string, { unsubscribe: () => void }>();

  constructor(private workspace: WorkspaceClient) {
    super();
  }

  startWatching(repoPath: string): void {
    if (this.subs.has(repoPath)) return;
    const sub = this.workspace.fileWatcher.watch.subscribe(
      { repoPath },
      {
        onData: (event) => {
          this.emit(event.kind, event as never);
        },
        onError: () => {},
      },
    );
    this.subs.set(repoPath, sub);
  }

  stopWatching(repoPath: string): void {
    const sub = this.subs.get(repoPath);
    if (!sub) return;
    sub.unsubscribe();
    this.subs.delete(repoPath);
  }

  /**
   * Tear down and re-create every active watch. The workspace-server child
   * respawns on a new port after a crash; the old SSE subscriptions keep
   * retrying the dead port forever, so the boot wiring calls this when the
   * server reports ready again.
   */
  resubscribeAll(): void {
    for (const repoPath of [...this.subs.keys()]) {
      this.stopWatching(repoPath);
      this.startWatching(repoPath);
    }
  }
}

// Single instance lock must be acquired FIRST before any other app setup
const additionalData = process.defaultApp ? { argv: process.argv } : undefined;
const gotTheLock = app.requestSingleInstanceLock(additionalData);
if (!gotTheLock) {
  app.quit();
  process.exit(0);
}

const RECOVERABLE_RENDER_REASONS = new Set([
  "abnormal-exit",
  "killed",
  "crashed",
  "oom",
  "integrity-failure",
  "memory-eviction",
]);
const CRASH_LOOP_WINDOW_MS = 30_000;
const CRASH_LOOP_THRESHOLD = 3;
const recentCrashTimestamps: number[] = [];

function isCrashLoop(): boolean {
  const now = Date.now();
  while (
    recentCrashTimestamps.length > 0 &&
    now - recentCrashTimestamps[0] > CRASH_LOOP_WINDOW_MS
  ) {
    recentCrashTimestamps.shift();
  }
  recentCrashTimestamps.push(now);
  return recentCrashTimestamps.length >= CRASH_LOOP_THRESHOLD;
}

function crashDiagnostics() {
  return {
    appUptimeSeconds: Math.round(process.uptime()),
    chromiumLogTail: readChromiumLogTail(),
    ...flattenMemorySnapshot(collectMemorySnapshot(() => app.getAppMetrics())),
  };
}

app.on("render-process-gone", (_event, webContents, details) => {
  const props = {
    source: "main",
    type: "render-process-gone",
    reason: details.reason,
    exitCode: String(details.exitCode),
    url: webContents.getURL(),
    title: webContents.getTitle(),
    webContentsId: String(webContents.id),
    ...crashDiagnostics(),
  };
  log.error("Renderer process gone", props);
  posthogNodeAnalytics.captureException(
    new Error(`Renderer process gone: ${details.reason}`),
    {
      ...props,
      $exception_fingerprint: ["render-process-gone", details.reason],
    },
  );
  posthogNodeAnalytics.flush().catch(() => {});

  if (RECOVERABLE_RENDER_REASONS.has(details.reason)) {
    if (isCrashLoop()) {
      log.error("Crash loop detected, stopping auto-recovery", {
        crashesInWindow: recentCrashTimestamps.length,
        windowMs: CRASH_LOOP_WINDOW_MS,
      });
      return;
    }
    log.info("Recovering from renderer crash", { reason: details.reason });
    const win = BrowserWindow.fromWebContents(webContents);
    if (!win || win.isDestroyed()) {
      log.warn("No window to recover");
      return;
    }
    setImmediate(() => {
      if (win.isDestroyed()) return;
      log.info("Reloading webContents");
      win.webContents.reload();
      log.info("Bringing window to foreground");
      win.show();
      win.moveTop();
      win.focus();
      app.focus({ steal: true });
    });
  }
});

app.on("child-process-gone", (_event, details) => {
  const props = {
    source: "main",
    type: "child-process-gone",
    processType: details.type,
    reason: details.reason,
    exitCode: String(details.exitCode),
    serviceName: details.serviceName ?? "",
    name: details.name ?? "",
    ...crashDiagnostics(),
  };
  log.error("Child process gone", props);
  posthogNodeAnalytics.captureException(
    new Error(`Child process gone (${details.type}): ${details.reason}`),
    {
      ...props,
      $exception_fingerprint: [
        "child-process-gone",
        details.type,
        details.reason,
      ],
    },
  );
  posthogNodeAnalytics.flush().catch(() => {});
});

async function initializeServices(): Promise<void> {
  initDevToolbar();

  container.get<DatabaseService>(DATABASE_SERVICE);
  container.get<OAuthService>(OAUTH_SERVICE);
  const authService = container.get<AuthService>(AUTH_SERVICE);
  container.get<NotificationService>(NOTIFICATION_SERVICE);
  container.get<UpdatesService>(UPDATES_SERVICE);
  container.get<TaskLinkService>(TASK_LINK_SERVICE);
  container.get<InboxLinkService>(INBOX_LINK_SERVICE);
  container.get<ScoutLinkService>(SCOUT_LINK_SERVICE);
  container.get<NewTaskLinkService>(NEW_TASK_LINK_SERVICE);
  container.get<ApprovalLinkService>(APPROVAL_LINK_SERVICE);
  // Eagerly resolved so their constructors register the `canvas` / `channel`
  // deep-link handlers at boot, before any link arrives.
  container.get<CanvasLinkService>(CANVAS_LINK_SERVICE);
  container.get<ChannelLinkService>(CHANNEL_LINK_SERVICE);
  container.get<GitHubIntegrationService>(GITHUB_INTEGRATION_SERVICE);
  container.get<SlackIntegrationService>(SLACK_INTEGRATION_SERVICE);
  container.get<ExternalAppsService>(EXTERNAL_APPS_SERVICE);
  container.get<PosthogPluginService>(POSTHOG_PLUGIN_SERVICE);
  // Eagerly start the Discord presence service so it connects when enabled.
  container.get<DiscordPresenceService>(DISCORD_PRESENCE_SERVICE);

  await authService.initialize();

  // Initialize workspace branch watcher for live branch rename detection
  const workspaceService = container.get<WorkspaceService>(WORKSPACE_SERVICE);
  workspaceService.initBranchWatcher();

  const suspensionService =
    container.get<SuspensionService>(SUSPENSION_SERVICE);
  suspensionService.startInactivityChecker();

  // Track app started event
  posthogNodeAnalytics.track(ANALYTICS_EVENTS.APP_STARTED);
}

// ========================================================
// App lifecycle
// ========================================================

// Register deep link handlers
registerDeepLinkHandlers();

// Initialize PostHog analytics
posthogNodeAnalytics.initialize();

// Must wrap fetch before DevNetworkService.install() (post-ready, dev toolbar)
// so it stays the innermost layer; otherwise toggling dev mode off restores
// native fetch and silently drops network.log capture.
installMainFetchLogging();

app.whenReady().then(async () => {
  if (
    process.platform === "darwin" &&
    app.isPackaged &&
    isMacosPackagedUnsafeBundleLocation(app.getAppPath(), process.execPath)
  ) {
    const appPath = app.getAppPath();
    const exePath = process.execPath;
    const bundleRoot = exePath.replace(/\/Contents\/MacOS\/[^/]+$/, "");
    log.warn(
      "Refusing to start: packaged app is on App Translocation or a read-only non-root volume",
      { appPath, exePath },
    );
    dialog.showMessageBoxSync({
      type: "warning",
      title: "Move PostHog to Applications",
      message: `PostHog is running from a location with read-only access:\n\n${bundleRoot}`,
      detail:
        "After quitting, move PostHog to your Applications folder, then open it from there.",
      buttons: ["Quit"],
      defaultId: 0,
    });
    app.quit();
    return;
  }

  const commit = __BUILD_COMMIT__ ?? "dev";
  const buildDate = __BUILD_DATE__ ?? "dev";
  log.info(
    [
      `PostHog electron v${app.getVersion()} booting up`,
      `Commit: ${commit}`,
      `Date: ${buildDate}`,
      `Electron: ${process.versions.electron}`,
      `Chromium: ${process.versions.chrome}`,
      `Node.js: ${process.versions.node}`,
      `V8: ${process.versions.v8}`,
      `OS: ${process.platform} ${process.arch} ${os.release()}`,
    ].join(" | "),
  );
  log.info(
    `Logs: main=${getLogFilePath()} chromium=${getChromiumLogFilePath() ?? "(disabled)"} network=${getNetworkLogFilePath()}`,
  );
  ensureClaudeConfigDir();
  setupExternalLinkPermissionHandlers(session.fromPartition("persist:main"));
  registerMcpSandboxProtocol();
  installRendererNetworkLogging(
    session.fromPartition("persist:main").webRequest,
    container.get<DevNetworkService>(DEV_NETWORK_SERVICE),
  );
  createWindow();

  const wsServer = container.get<WorkspaceServerService>(
    WORKSPACE_SERVER_SERVICE,
  );
  await wsServer.start();
  // The workspace-server child respawns on a new port/secret after a crash;
  // a reconnecting client follows the current connection so main-process
  // callers don't keep hitting the dead port for the rest of the session.
  const workspaceClient = createReconnectingWorkspaceClient(() =>
    wsServer.getConnection(),
  );
  container.bind(WORKSPACE_CLIENT).toConstantValue(workspaceClient);
  container.bind(GIT_WORKSPACE_CLIENT).toConstantValue(workspaceClient);
  container.bind(CONNECTIVITY_CLIENT).toConstantValue(workspaceClient);
  container.bind(ENVIRONMENT_CLIENT).toConstantValue(workspaceClient);
  const fileWatcherBridge = new FileWatcherBridge(workspaceClient);
  // Re-establish live watches after a workspace-server respawn — the old SSE
  // subscriptions keep retrying the dead port and never recover on their own.
  wsServer.on(WorkspaceServerEvent.StatusChanged, ({ status }) => {
    if (status === WorkspaceServerStatus.Ready) {
      fileWatcherBridge.resubscribeAll();
    }
  });
  container.bind(FILE_WATCHER_SERVICE).toConstantValue(fileWatcherBridge);
  container.bind(FILE_WATCHER_CONTROL).toConstantValue(fileWatcherBridge);
  container.bind(FOCUS_WORKSPACE_CLIENT).toConstantValue(workspaceClient);
  container.bind(FOCUS_SESSION_STORE).toConstantValue(focusSessionStore);
  container.bind(FOCUS_WORKTREE_PATHS).toConstantValue(focusWorktreePaths);
  container.load(focusHostModule);
  const fsCapability: FsCapability = {
    listRepoFiles: (repoPath, query, limit) =>
      workspaceClient.fs.listRepoFiles.query({ repoPath, query, limit }),
    readRepoFile: (repoPath, filePath) =>
      workspaceClient.fs.readRepoFile.query({ repoPath, filePath }),
    readRepoFiles: (repoPath, filePaths) =>
      workspaceClient.fs.readRepoFiles.query({ repoPath, filePaths }),
    readRepoFileBounded: (repoPath, filePath, maxLines) =>
      workspaceClient.fs.readRepoFileBounded.query({
        repoPath,
        filePath,
        maxLines,
      }),
    readRepoFilesBounded: (repoPath, filePaths, maxLines) =>
      workspaceClient.fs.readRepoFilesBounded.query({
        repoPath,
        filePaths,
        maxLines,
      }),
    readAbsoluteFile: (filePath) =>
      workspaceClient.fs.readAbsoluteFile.query({ filePath }),
    readFileAsBase64: (filePath) =>
      workspaceClient.fs.readFileAsBase64.query({ filePath }),
    writeRepoFile: async (repoPath, filePath, content) => {
      await workspaceClient.fs.writeRepoFile.mutate({
        repoPath,
        filePath,
        content,
      });
    },
  };
  container.bind(MAIN_FS_SERVICE).toConstantValue(fsCapability);
  container.bind(FS_SERVICE).toService(MAIN_FS_SERVICE);
  await initializeServices();
  initializeDeepLinks();

  if (process.env.POSTHOG_E2E_UPDATE_FEED) {
    const updates = container.get<UpdatesService>(UPDATES_SERVICE);
    Object.assign(globalThis, {
      __e2eUpdates: {
        check: () => updates.checkForUpdates(),
        download: () => updates.requestDownload(),
        install: () => updates.installUpdate(),
        status: () => updates.getStatus(),
      },
    });
    log.info("E2E update hook installed on globalThis.__e2eUpdates");
  }
});

app.on("window-all-closed", () => {
  app.quit();
});

const teardownContainer = async (): Promise<void> => {
  try {
    await container.unbindAll();
  } catch (error) {
    log.warn("Failed to unbind container", error);
  }
};

app.on("before-quit", async (event) => {
  try {
    container.get<WorkspaceServerService>(WORKSPACE_SERVER_SERVICE).stop();
  } catch {}
  let lifecycleService: AppLifecycleService;
  try {
    lifecycleService = container.get<AppLifecycleService>(
      APP_LIFECYCLE_SERVICE,
    );
  } catch {
    // Container already torn down (e.g. second quit during shutdown), let Electron quit
    return;
  }

  // If quitting to install an update, don't block and let the updater handle it
  // we already gracefully shutdown the app in the updates service when the update is ready
  if (lifecycleService.isQuittingForUpdate) {
    return;
  }

  // If shutdown is already in progress, force-kill immediately
  if (lifecycleService.isShuttingDown) {
    lifecycleService.forceKill();
  }

  event.preventDefault();

  await lifecycleService.gracefulExit(teardownContainer);
});

const handleShutdownSignal = async (signal: string) => {
  log.info(`Received ${signal}, starting shutdown`);
  try {
    const lifecycleService = container.get<AppLifecycleService>(
      APP_LIFECYCLE_SERVICE,
    );
    if (lifecycleService.isShuttingDown) {
      log.warn(`${signal} received during shutdown, forcing exit`);
      process.exit(1);
    }
    await lifecycleService.shutdown();
    await teardownContainer();
  } catch (_err) {
    // Container torn down or shutdown failed
  }
  process.exit(0);
};

// ========================================================
// Process signal handlers
// ========================================================

process.on("SIGTERM", () => handleShutdownSignal("SIGTERM"));
process.on("SIGINT", () => handleShutdownSignal("SIGINT"));
if (process.platform !== "win32") {
  process.on("SIGHUP", () => handleShutdownSignal("SIGHUP"));
}

// A deliberate Ctrl+C during an interactive prompt makes Node's readline
// SIGINT trap reject the pending prompt with an AbortError (code ABORT_ERR).
// It is user-initiated, not a crash, so don't report it as an uncaught error.
const isAbortError = (error: unknown): boolean =>
  error instanceof Error &&
  (error.name === "AbortError" ||
    (error as NodeJS.ErrnoException).code === "ABORT_ERR");

process.on("uncaughtException", (error) => {
  if (error.message === "write EIO") {
    log.transports.console.level = false;
    return;
  }
  if (isAbortError(error)) {
    log.debug("Ignoring user-initiated abort", error);
    return;
  }
  log.error("Uncaught exception", error);
  posthogNodeAnalytics.captureException(error, {
    source: "main",
    type: "uncaughtException",
  });
});

process.on("unhandledRejection", (reason) => {
  if (isAbortError(reason)) {
    log.debug("Ignoring user-initiated abort", reason);
    return;
  }
  log.error("Unhandled rejection", reason);
  const error = reason instanceof Error ? reason : new Error(String(reason));
  posthogNodeAnalytics.captureException(error, {
    source: "main",
    type: "unhandledRejection",
  });
});
