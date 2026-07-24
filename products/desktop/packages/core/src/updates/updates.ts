import { ROOT_LOGGER, type RootLogger } from "@posthog/di/logger";
import {
  APP_LIFECYCLE_SERVICE,
  type IAppLifecycle,
} from "@posthog/platform/app-lifecycle";
import { APP_META_SERVICE, type IAppMeta } from "@posthog/platform/app-meta";
import {
  type IMainWindow,
  MAIN_WINDOW_SERVICE,
} from "@posthog/platform/main-window";
import {
  type IUpdater,
  UPDATER_SERVICE,
  type UpdateAvailableInfo,
  type UpdateDownloadProgress,
} from "@posthog/platform/updater";
import {
  type SagaLogger,
  TypedEventEmitter,
  withTimeout,
} from "@posthog/shared";
import { inject, injectable, postConstruct, preDestroy } from "inversify";
import { type IUpdateLifecycle, UPDATE_LIFECYCLE_SERVICE } from "./identifiers";
import {
  type CheckForUpdatesOutput,
  type InstallUpdateOutput,
  UpdatesEvent,
  type UpdatesEvents,
  type UpdatesStatusPayload,
} from "./schemas";

type CheckSource = "user" | "periodic";
type UpdateState =
  | "idle"
  | "checking"
  | "available"
  | "downloading"
  | "ready"
  | "installing"
  | "error";
type TransitionContext = {
  source?: CheckSource;
  skippedBecauseUpdateStaged?: boolean;
  reason?: string;
  incomingVersion?: string | null;
  error?: string;
};

@injectable()
export class UpdatesService extends TypedEventEmitter<UpdatesEvents> {
  private static readonly CHECK_INTERVAL_MS = 60 * 60 * 1000; // 1 hour
  private static readonly CHECK_TIMEOUT_MS = 60 * 1000; // 1 minute timeout for checks
  // Must exceed AppLifecycleService.PENDING_CREATION_WAIT_MS (10s) plus its
  // LEAVE_FULLSCREEN_TIMEOUT_MS (3s) plus teardown headroom, or the waits
  // inside partial shutdown get cut off and quitAndInstall proceeds without
  // any teardown at all.
  private static readonly INSTALL_SHUTDOWN_TIMEOUT_MS = 20_000;

  @inject(UPDATE_LIFECYCLE_SERVICE)
  private lifecycle!: IUpdateLifecycle;

  @inject(ROOT_LOGGER)
  private rootLogger!: RootLogger;

  private logScoped: SagaLogger | null = null;

  private get log(): SagaLogger {
    if (this.logScoped === null) {
      this.logScoped = this.rootLogger.scope("updates");
    }
    return this.logScoped;
  }

  @inject(UPDATER_SERVICE)
  private updater!: IUpdater;

  @inject(APP_LIFECYCLE_SERVICE)
  private appLifecycle!: IAppLifecycle;

  @inject(APP_META_SERVICE)
  private appMeta!: IAppMeta;

  @inject(MAIN_WINDOW_SERVICE)
  private mainWindow!: IMainWindow;

  private state: UpdateState = "idle";
  private pendingNotification = false;
  private checkTimeoutId: ReturnType<typeof setTimeout> | null = null;
  private checkIntervalId: ReturnType<typeof setInterval> | null = null;
  private downloadedVersion: string | null = null;
  private notifiedVersion: string | null = null;
  private lastError: string | null = null;
  private initialized = false;
  private unsubscribes: Array<() => void> = [];
  private availableInfo: UpdateAvailableInfo | null = null;
  private downloadProgress: UpdateDownloadProgress | null = null;
  private autoDownloadEnabled = false;
  private lastProgressEmit = 0;

  get hasUpdateReady(): boolean {
    return this.isUpdateStaged();
  }

  private isUpdateStaged(): boolean {
    return this.state === "ready" || this.state === "installing";
  }

  get isEnabled(): boolean {
    return this.updater.isSupported();
  }

  @postConstruct()
  init(): void {
    if (!this.isEnabled) {
      this.log.info("Auto updates not enabled for this host");
      return;
    }

    this.unsubscribes.push(
      this.mainWindow.onFocus(() => this.flushPendingNotification()),
    );
    this.appLifecycle.whenReady().then(() => this.setupAutoUpdater());
  }

  triggerMenuCheck(): void {
    this.emit(UpdatesEvent.CheckFromMenu, true);
  }

  setAutoDownloadEnabled(enabled: boolean): void {
    this.autoDownloadEnabled = enabled;
    if (this.isEnabled) {
      this.updater.setAutoDownload(enabled);
    }
    this.log.info("Auto-download preference updated", { enabled });

    if (enabled && this.state === "available") {
      this.requestDownload();
    }
  }

  requestDownload(): void {
    if (this.state !== "available") {
      this.log.warn("requestDownload called but no update is available", {
        state: this.state,
      });
      return;
    }
    this.transitionTo("downloading", {
      reason: "user requested download",
      incomingVersion: this.availableInfo?.version ?? null,
    });
    this.log.info("Downloading update...", {
      version: this.availableInfo?.version,
    });
    this.updater.download();
    this.emitStatus(this.downloadingStatusPayload());
  }

  getStatus(): UpdatesStatusPayload {
    if (this.state === "checking") {
      return { checking: true };
    }

    if (this.state === "available") {
      return this.availableStatusPayload();
    }

    if (this.state === "downloading") {
      return this.downloadingStatusPayload();
    }

    if (this.isUpdateStaged()) {
      return this.stagedStatusPayload();
    }

    if (this.state === "error") {
      return {
        checking: false,
        error: this.lastError ?? "Update check failed. Please try again.",
      };
    }

    return { checking: false };
  }

  checkForUpdates(source: CheckSource = "user"): CheckForUpdatesOutput {
    if (!this.isEnabled) {
      const reason = !this.appMeta.isProduction
        ? "Updates only available in packaged builds"
        : "Auto updates only supported on macOS and Windows";
      return { success: false, errorMessage: reason, errorCode: "disabled" };
    }

    if (this.isUpdateStaged()) {
      this.logStateTransition(this.state, {
        source,
        skippedBecauseUpdateStaged: true,
        reason: "check skipped because update is already staged",
      });

      if (source === "user") {
        this.pendingNotification = true;
        this.flushPendingNotification();
        this.emitStatus(this.stagedStatusPayload());
      }

      return { success: true };
    }

    if (source === "periodic" && this.state === "available") {
      this.logStateTransition(this.state, {
        source,
        reason: "periodic check skipped because an update is already available",
      });
      return { success: true };
    }

    if (this.state === "checking" || this.state === "downloading") {
      return {
        success: false,
        errorMessage: "Already checking for updates",
        errorCode: "already_checking",
      };
    }

    this.transitionTo("checking", { source });
    this.emitStatus({ checking: true });
    this.performCheck();

    return { success: true };
  }

  async installUpdate(): Promise<InstallUpdateOutput> {
    if (this.state === "installing") {
      this.logStateTransition("installing", {
        skippedBecauseUpdateStaged: true,
        reason: "install already in progress",
      });
      return { installed: true };
    }

    if (this.state !== "ready") {
      this.log.warn("installUpdate called but no update is ready", {
        state: this.state,
      });
      return { installed: false };
    }

    this.log.info("Installing update and restarting...", {
      downloadedVersion: this.downloadedVersion,
    });

    try {
      this.transitionTo("installing", { reason: "install requested" });
      this.emitStatus(this.stagedStatusPayload());
      this.lifecycle.setQuittingForUpdate();
      const cleanupResult = await withTimeout(
        this.lifecycle.shutdownWithoutContainer(),
        UpdatesService.INSTALL_SHUTDOWN_TIMEOUT_MS,
      );
      if (cleanupResult.result === "timeout") {
        this.log.warn("Partial shutdown timed out before update install", {
          timeoutMs: UpdatesService.INSTALL_SHUTDOWN_TIMEOUT_MS,
          downloadedVersion: this.downloadedVersion,
        });
      }
      this.updater.quitAndInstall();
      return { installed: true };
    } catch (error) {
      this.log.error("Failed to quit and install update", { error });
      this.lifecycle.clearQuittingForUpdate();
      this.transitionTo("ready", {
        reason: "install handoff failed",
        error: error instanceof Error ? error.message : String(error),
      });
      this.emitStatus(this.stagedStatusPayload());
      return { installed: false };
    }
  }

  private setupAutoUpdater(): void {
    if (this.initialized) {
      this.log.warn("setupAutoUpdater called multiple times, ignoring");
      return;
    }

    this.initialized = true;
    this.log.info("Setting up auto updater", {
      currentVersion: this.appMeta.version,
      platform: this.appMeta.platform,
      arch: this.appMeta.arch,
    });

    this.unsubscribes.push(
      this.updater.onError((error) => this.handleError(error)),
      this.updater.onCheckStart(() => this.log.info("Checking for updates...")),
      this.updater.onUpdateAvailable((info) =>
        this.handleUpdateAvailable(info),
      ),
      this.updater.onDownloadProgress((progress) =>
        this.handleDownloadProgress(progress),
      ),
      this.updater.onNoUpdate(() => this.handleNoUpdate()),
      this.updater.onUpdateDownloaded((releaseName) =>
        this.handleUpdateDownloaded(releaseName),
      ),
    );

    this.checkForUpdates("periodic");

    this.checkIntervalId = setInterval(
      () => this.checkForUpdates("periodic"),
      UpdatesService.CHECK_INTERVAL_MS,
    );
  }

  private stagedStatusPayload(): UpdatesStatusPayload {
    return {
      checking: false,
      updateReady: true,
      installing: this.state === "installing",
      version: this.downloadedVersion ?? undefined,
    };
  }

  private availableStatusPayload(): UpdatesStatusPayload {
    return {
      checking: false,
      available: true,
      availableVersion: this.availableInfo?.version,
      releaseNotes: this.availableInfo?.releaseNotes ?? undefined,
      releaseDate: this.availableInfo?.releaseDate,
      downloadSizeBytes: this.availableInfo?.sizeBytes ?? undefined,
    };
  }

  private downloadingStatusPayload(): UpdatesStatusPayload {
    return {
      checking: true,
      downloading: true,
      availableVersion: this.availableInfo?.version,
      releaseNotes: this.availableInfo?.releaseNotes ?? undefined,
      releaseDate: this.availableInfo?.releaseDate,
      downloadPercent: this.downloadProgress?.percent,
      bytesPerSecond: this.downloadProgress?.bytesPerSecond,
      downloadSizeBytes: this.availableInfo?.sizeBytes ?? undefined,
    };
  }

  private handleError(error: Error): void {
    this.clearCheckTimeout();
    this.log.error("Auto update error", {
      message: error.message,
      stack: error.stack,
      state: this.state,
    });

    if (this.isUpdateStaged()) {
      this.logStateTransition(this.state, {
        skippedBecauseUpdateStaged: true,
        reason: "updater error ignored because update is staged",
        error: error.message,
      });
      return;
    }

    if (this.state === "checking" || this.state === "downloading") {
      this.lastError = error.message;
      this.transitionTo("error", { error: error.message });
      this.emitStatus({
        checking: false,
        error: error.message,
      });
    }
  }

  private handleUpdateAvailable(info: UpdateAvailableInfo): void {
    if (this.isUpdateStaged()) {
      this.log.info(
        "Ignoring update-available because an update is already staged",
        {
          downloadedVersion: this.downloadedVersion,
        },
      );
      return;
    }

    this.clearCheckTimeout();
    this.availableInfo = info;
    this.downloadProgress = null;

    if (this.autoDownloadEnabled) {
      this.transitionTo("downloading", {
        reason: "update available (auto-download)",
        incomingVersion: info.version,
      });
      this.log.info("Update available, auto-downloading...", {
        version: info.version,
      });
      this.updater.download();
      this.emitStatus(this.downloadingStatusPayload());
      return;
    }

    this.transitionTo("available", {
      reason: "update available",
      incomingVersion: info.version,
    });
    this.log.info("Update available, awaiting user download", {
      version: info.version,
    });
    this.emitStatus(this.availableStatusPayload());
  }

  private handleDownloadProgress(progress: UpdateDownloadProgress): void {
    if (this.state !== "downloading") {
      return;
    }
    this.downloadProgress = progress;
    const now = Date.now();
    if (now - this.lastProgressEmit >= 400 || progress.percent >= 100) {
      this.lastProgressEmit = now;
      this.emitStatus(this.downloadingStatusPayload());
    }
  }

  private handleNoUpdate(): void {
    this.clearCheckTimeout();

    if (this.isUpdateStaged()) {
      this.log.info("Ignoring update-not-available because update is staged", {
        downloadedVersion: this.downloadedVersion,
      });
      return;
    }

    this.log.info("No updates available", {
      currentVersion: this.appMeta.version,
    });
    if (this.state === "checking" || this.state === "downloading") {
      this.transitionTo("idle", { reason: "no update available" });
      this.emitStatus({
        checking: false,
        upToDate: true,
        version: this.appMeta.version,
      });
    }
  }

  private handleUpdateDownloaded(version?: string): void {
    this.clearCheckTimeout();

    if (this.isUpdateStaged()) {
      this.log.info("Ignoring duplicate update-downloaded event", {
        existingVersion: this.downloadedVersion,
        incomingVersion: version,
      });
      return;
    }

    this.downloadedVersion = version ?? null;
    this.transitionTo("ready", {
      reason: "update downloaded",
      incomingVersion: version ?? null,
    });
    this.clearCheckInterval();
    this.emitStatus(this.stagedStatusPayload());

    this.log.info("Update downloaded, awaiting user confirmation", {
      currentVersion: this.appMeta.version,
      downloadedVersion: this.downloadedVersion,
    });

    if (this.notifiedVersion !== this.downloadedVersion) {
      this.pendingNotification = true;
      this.flushPendingNotification();
    } else {
      this.log.info("Skipping notification - same version already notified", {
        version: this.downloadedVersion,
      });
    }
  }

  private flushPendingNotification(): void {
    if (this.state === "ready" && this.pendingNotification) {
      this.log.info("Notifying user that update is ready", {
        downloadedVersion: this.downloadedVersion,
      });
      this.emit(UpdatesEvent.Ready, { version: this.downloadedVersion });
      this.pendingNotification = false;
      this.notifiedVersion = this.downloadedVersion;
    }
  }

  private emitStatus(status: UpdatesStatusPayload): void {
    this.emit(UpdatesEvent.Status, status);
  }

  private performCheck(): void {
    this.clearCheckTimeout();

    this.checkTimeoutId = setTimeout(() => {
      if (this.state === "checking" || this.state === "downloading") {
        const timeoutSeconds = UpdatesService.CHECK_TIMEOUT_MS / 1000;
        const message = "Update check timed out. Please try again.";
        this.log.warn(`Update check timed out after ${timeoutSeconds} seconds`);
        this.lastError = message;
        this.transitionTo("error", { error: message });
        this.emitStatus({ checking: false, error: message });
      }
    }, UpdatesService.CHECK_TIMEOUT_MS);

    try {
      this.updater.check();
    } catch (error) {
      this.clearCheckTimeout();
      this.log.error("Failed to check for updates", { error });
      this.lastError = "Failed to check for updates. Please try again.";
      this.transitionTo("error", {
        error: error instanceof Error ? error.message : String(error),
      });
      this.emitStatus({
        checking: false,
        error: "Failed to check for updates. Please try again.",
      });
    }
  }

  private transitionTo(
    state: UpdateState,
    context: TransitionContext = {},
  ): void {
    this.logStateTransition(state, context);
    this.state = state;
    if (state !== "error") {
      this.lastError = null;
    }
  }

  private logStateTransition(
    toState: UpdateState,
    context: TransitionContext = {},
  ): void {
    this.log.info("Update state transition", {
      source: context.source,
      fromState: this.state,
      toState,
      downloadedVersion: this.downloadedVersion,
      skippedBecauseUpdateStaged: context.skippedBecauseUpdateStaged ?? false,
      reason: context.reason,
      incomingVersion: context.incomingVersion,
      error: context.error,
    });
  }

  private clearCheckTimeout(): void {
    if (this.checkTimeoutId) {
      clearTimeout(this.checkTimeoutId);
      this.checkTimeoutId = null;
    }
  }

  private clearCheckInterval(): void {
    if (this.checkIntervalId) {
      clearInterval(this.checkIntervalId);
      this.checkIntervalId = null;
    }
  }

  @preDestroy()
  shutdown(): void {
    this.clearCheckTimeout();
    this.clearCheckInterval();
    for (const unsub of this.unsubscribes) unsub();
    this.unsubscribes = [];
  }
}
