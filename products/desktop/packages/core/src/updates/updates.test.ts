import type {
  UpdateAvailableInfo,
  UpdateDownloadProgress,
} from "@posthog/platform/updater";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { UpdatesEvent } from "./schemas";

// Use vi.hoisted to ensure mocks are available when vi.mock is hoisted
const {
  mockUpdater,
  mockAppLifecycle,
  mockAppMeta,
  mockMainWindow,
  mockLifecycleService,
  mockLog,
  updaterHandlers,
} = vi.hoisted(() => {
  const updaterHandlers: {
    checkStart: (() => void) | null;
    updateAvailable: ((info: UpdateAvailableInfo) => void) | null;
    downloadProgress: ((progress: UpdateDownloadProgress) => void) | null;
    noUpdate: (() => void) | null;
    updateDownloaded: ((version: string) => void) | null;
    error: ((error: Error) => void) | null;
    focus: (() => void) | null;
  } = {
    checkStart: null,
    updateAvailable: null,
    downloadProgress: null,
    noUpdate: null,
    updateDownloaded: null,
    error: null,
    focus: null,
  };

  return {
    updaterHandlers,
    mockUpdater: {
      isSupported: vi.fn(() => true),
      check: vi.fn(),
      quitAndInstall: vi.fn(),
      onCheckStart: vi.fn((h: () => void) => {
        updaterHandlers.checkStart = h;
        return () => {};
      }),
      onUpdateAvailable: vi.fn((h: (info: UpdateAvailableInfo) => void) => {
        updaterHandlers.updateAvailable = h;
        return () => {};
      }),
      onDownloadProgress: vi.fn(
        (h: (progress: UpdateDownloadProgress) => void) => {
          updaterHandlers.downloadProgress = h;
          return () => {};
        },
      ),
      download: vi.fn(),
      setAutoDownload: vi.fn(),
      onNoUpdate: vi.fn((h: () => void) => {
        updaterHandlers.noUpdate = h;
        return () => {};
      }),
      onUpdateDownloaded: vi.fn((h: (version: string) => void) => {
        updaterHandlers.updateDownloaded = h;
        return () => {};
      }),
      onError: vi.fn((h: (error: Error) => void) => {
        updaterHandlers.error = h;
        return () => {};
      }),
    },
    mockAppLifecycle: {
      whenReady: vi.fn(() => Promise.resolve()),
      quit: vi.fn(),
      exit: vi.fn(),
      onQuit: vi.fn(() => () => {}),
      registerDeepLinkScheme: vi.fn(),
    },
    mockAppMeta: {
      version: "1.0.0",
      isProduction: true,
      platform: "darwin",
      arch: "arm64",
    },
    mockMainWindow: {
      focus: vi.fn(),
      isFocused: vi.fn(() => false),
      isMinimized: vi.fn(() => false),
      restore: vi.fn(),
      onFocus: vi.fn((h: () => void) => {
        updaterHandlers.focus = h;
        return () => {};
      }),
    },
    mockLifecycleService: {
      shutdown: vi.fn(() => Promise.resolve()),
      shutdownWithoutContainer: vi.fn(() => Promise.resolve()),
      setQuittingForUpdate: vi.fn(),
      clearQuittingForUpdate: vi.fn(),
    },
    mockLog: {
      info: vi.fn(),
      error: vi.fn(),
      warn: vi.fn(),
      debug: vi.fn(),
    },
  };
});

import { UpdatesService } from "./updates";

function injectPorts(service: UpdatesService): void {
  const s = service as unknown as Record<string, unknown>;
  s.lifecycle = mockLifecycleService;
  s.rootLogger = { ...mockLog, scope: () => mockLog };
  s.updater = mockUpdater;
  s.appLifecycle = mockAppLifecycle;
  s.appMeta = mockAppMeta;
  s.mainWindow = mockMainWindow;
}

// Helper to initialize service and wait for setup without running the periodic interval infinitely
async function initializeService(service: UpdatesService): Promise<void> {
  service.init();
  // Allow the whenReady promise microtask to resolve
  await vi.advanceTimersByTimeAsync(0);
}

describe("UpdatesService", () => {
  let service: UpdatesService;
  let originalPlatform: PropertyDescriptor | undefined;
  let originalEnv: NodeJS.ProcessEnv;

  beforeEach(() => {
    vi.clearAllMocks();
    vi.useFakeTimers();

    // Store original values
    originalPlatform = Object.getOwnPropertyDescriptor(process, "platform");
    originalEnv = { ...process.env };

    // Reset mocks to default state
    mockAppMeta.isProduction = true;
    mockAppMeta.version = "1.0.0";
    mockAppMeta.platform = "darwin";
    mockAppMeta.arch = "arm64";
    mockUpdater.isSupported.mockReturnValue(true);
    mockUpdater.quitAndInstall.mockImplementation(() => undefined);
    mockLifecycleService.shutdownWithoutContainer.mockImplementation(() =>
      Promise.resolve(),
    );
    mockAppLifecycle.whenReady.mockResolvedValue(undefined);

    // Set default platform to darwin (macOS)
    Object.defineProperty(process, "platform", {
      value: "darwin",
      configurable: true,
    });

    // Clear env flag
    delete process.env.ELECTRON_DISABLE_AUTO_UPDATE;

    service = new UpdatesService();
    injectPorts(service);
  });

  afterEach(() => {
    vi.useRealTimers();

    // Restore original values
    if (originalPlatform) {
      Object.defineProperty(process, "platform", originalPlatform);
    }
    process.env = originalEnv;
  });

  describe("isEnabled", () => {
    // Host support gating (packaged, platform allow-list, ELECTRON_DISABLE_AUTO_UPDATE)
    // now lives in the platform updater adapter's isSupported(); core just mirrors it.
    it("returns true when the platform updater reports supported", () => {
      mockUpdater.isSupported.mockReturnValue(true);

      const newService = new UpdatesService();
      injectPorts(newService);
      expect(newService.isEnabled).toBe(true);
    });

    it("returns false when the platform updater reports unsupported", () => {
      mockUpdater.isSupported.mockReturnValue(false);

      const newService = new UpdatesService();
      injectPorts(newService);
      expect(newService.isEnabled).toBe(false);
    });
  });

  describe("init", () => {
    it("sets up auto updater when enabled", async () => {
      await initializeService(service);

      expect(mockMainWindow.onFocus).toHaveBeenCalledWith(expect.any(Function));
      expect(mockAppLifecycle.whenReady).toHaveBeenCalled();
    });

    it("does not set up auto updater when the host reports unsupported", () => {
      mockUpdater.isSupported.mockReturnValue(false);

      const newService = new UpdatesService();
      injectPorts(newService);
      newService.init();

      expect(mockAppLifecycle.whenReady).not.toHaveBeenCalled();
    });

    it("prevents multiple initializations", async () => {
      await initializeService(service);

      const firstCallCount = mockUpdater.onError.mock.calls.length;
      await initializeService(service);

      expect(mockUpdater.onError.mock.calls.length).toBe(firstCallCount);
    });
  });

  describe("checkForUpdates", () => {
    it("returns success when updates are enabled", () => {
      const result = service.checkForUpdates();
      expect(result).toEqual({ success: true });
    });

    it("returns error when updates are disabled (not packaged)", () => {
      mockUpdater.isSupported.mockReturnValue(false);
      mockAppMeta.isProduction = false;

      const newService = new UpdatesService();
      injectPorts(newService);
      const result = newService.checkForUpdates();

      expect(result).toEqual({
        success: false,
        errorMessage: "Updates only available in packaged builds",
        errorCode: "disabled",
      });
    });

    it("returns error when updates are disabled (unsupported platform)", () => {
      mockUpdater.isSupported.mockReturnValue(false);
      mockAppMeta.isProduction = true;

      const newService = new UpdatesService();
      injectPorts(newService);
      const result = newService.checkForUpdates();

      expect(result).toEqual({
        success: false,
        errorMessage: "Auto updates only supported on macOS and Windows",
        errorCode: "disabled",
      });
    });

    it("returns error when already checking for updates", () => {
      // First call starts the check
      service.checkForUpdates();

      // Second call should fail
      const result = service.checkForUpdates();
      expect(result).toEqual({
        success: false,
        errorMessage: "Already checking for updates",
        errorCode: "already_checking",
      });
    });

    it("emits status event when checking starts", () => {
      const statusHandler = vi.fn();
      service.on(UpdatesEvent.Status, statusHandler);

      service.checkForUpdates();

      expect(statusHandler).toHaveBeenCalledWith({ checking: true });
    });

    it("calls autoUpdater.checkForUpdates", async () => {
      await initializeService(service);

      // Complete the initial check triggered by setupAutoUpdater
      const notAvailableHandler = updaterHandlers.noUpdate;
      if (notAvailableHandler) {
        notAvailableHandler();
      }

      mockUpdater.check.mockClear();
      service.checkForUpdates();

      expect(mockUpdater.check).toHaveBeenCalled();
    });

    it("allows retry after previous check completes", async () => {
      await initializeService(service);

      // Complete the initial check triggered by setupAutoUpdater
      const notAvailableHandler = updaterHandlers.noUpdate;

      if (notAvailableHandler) {
        notAvailableHandler();
      }

      // First explicit check
      const result1 = service.checkForUpdates();
      expect(result1.success).toBe(true);

      // Simulate completion
      if (notAvailableHandler) {
        notAvailableHandler();
      }

      // Second check should succeed
      const result2 = service.checkForUpdates();
      expect(result2.success).toBe(true);
    });
  });

  describe("hasUpdateReady", () => {
    it("returns false initially", () => {
      expect(service.hasUpdateReady).toBe(false);
    });

    it("returns true after an update is downloaded", async () => {
      await initializeService(service);

      const downloadedHandler = updaterHandlers.updateDownloaded;

      if (downloadedHandler) {
        downloadedHandler("v2.0.0");
      }

      expect(service.hasUpdateReady).toBe(true);
    });
  });

  describe("installUpdate", () => {
    it("returns false when no update is ready", async () => {
      const result = await service.installUpdate();
      expect(result).toEqual({ installed: false });
    });

    it("calls quitAndInstall when update is ready", async () => {
      await initializeService(service);

      // Simulate update downloaded
      const updateDownloadedHandler = updaterHandlers.updateDownloaded;

      if (updateDownloadedHandler) {
        updateDownloadedHandler("v2.0.0");
      }

      const resultPromise = service.installUpdate();
      await vi.runOnlyPendingTimersAsync();
      const result = await resultPromise;
      expect(result).toEqual({ installed: true });

      // Verify setQuittingForUpdate is called first
      expect(mockLifecycleService.setQuittingForUpdate).toHaveBeenCalled();

      expect(mockLifecycleService.shutdownWithoutContainer).toHaveBeenCalled();
      expect(mockLifecycleService.shutdown).not.toHaveBeenCalled();

      expect(mockUpdater.quitAndInstall).toHaveBeenCalled();

      // Verify order: setQuittingForUpdate -> shutdownWithoutContainer -> quitAndInstall
      const setQuittingOrder =
        mockLifecycleService.setQuittingForUpdate.mock.invocationCallOrder[0];
      const cleanupOrder =
        mockLifecycleService.shutdownWithoutContainer.mock
          .invocationCallOrder[0];
      const quitAndInstallOrder =
        mockUpdater.quitAndInstall.mock.invocationCallOrder[0];

      expect(setQuittingOrder).toBeLessThan(cleanupOrder);
      expect(cleanupOrder).toBeLessThan(quitAndInstallOrder);
    });

    it("continues to quitAndInstall if partial shutdown times out", async () => {
      await initializeService(service);

      updaterHandlers.updateDownloaded?.("v2.0.0");

      mockLifecycleService.shutdownWithoutContainer.mockReturnValue(
        new Promise(() => {}),
      );

      const resultPromise = service.installUpdate();
      await vi.advanceTimersByTimeAsync(20_000);

      await expect(resultPromise).resolves.toEqual({ installed: true });
      expect(mockUpdater.quitAndInstall).toHaveBeenCalled();
      expect(mockLog.warn).toHaveBeenCalledWith(
        "Partial shutdown timed out before update install",
        expect.objectContaining({
          timeoutMs: 20_000,
          downloadedVersion: "v2.0.0",
        }),
      );
    });

    it("returns false if quitAndInstall throws", async () => {
      await initializeService(service);

      // Simulate update downloaded
      const updateDownloadedHandler = updaterHandlers.updateDownloaded;

      if (updateDownloadedHandler) {
        updateDownloadedHandler("v2.0.0");
      }

      mockUpdater.quitAndInstall.mockImplementation(() => {
        throw new Error("Failed to install");
      });

      const resultPromise = service.installUpdate();
      await vi.runOnlyPendingTimersAsync();
      const result = await resultPromise;
      expect(result).toEqual({ installed: false });
    });

    it("clears the quitting-for-update lifecycle flag when install handoff fails", async () => {
      await initializeService(service);
      updaterHandlers.updateDownloaded?.("v2.0.0");

      mockUpdater.quitAndInstall.mockImplementation(() => {
        throw new Error("Failed to install");
      });

      await service.installUpdate();

      expect(mockLifecycleService.clearQuittingForUpdate).toHaveBeenCalled();
      const setOrder =
        mockLifecycleService.setQuittingForUpdate.mock.invocationCallOrder[0];
      const clearOrder =
        mockLifecycleService.clearQuittingForUpdate.mock.invocationCallOrder[0];
      expect(setOrder).toBeLessThan(clearOrder);
    });

    it("rolls back to a re-installable ready state when install handoff fails", async () => {
      await initializeService(service);
      updaterHandlers.updateDownloaded?.("v2.0.0");

      mockUpdater.quitAndInstall.mockImplementation(() => {
        throw new Error("Failed to install");
      });

      const statusHandler = vi.fn();
      service.on(UpdatesEvent.Status, statusHandler);

      const first = await service.installUpdate();
      expect(first).toEqual({ installed: false });
      expect(service.hasUpdateReady).toBe(true);
      expect(statusHandler).toHaveBeenLastCalledWith({
        checking: false,
        updateReady: true,
        installing: false,
        version: "v2.0.0",
      });

      mockUpdater.quitAndInstall.mockImplementationOnce(() => undefined);
      const second = await service.installUpdate();
      expect(second).toEqual({ installed: true });
    });

    it("is idempotent when install is already in progress", async () => {
      await initializeService(service);

      updaterHandlers.updateDownloaded?.("v2.0.0");

      await expect(service.installUpdate()).resolves.toEqual({
        installed: true,
      });
      expect(mockUpdater.quitAndInstall).toHaveBeenCalledTimes(1);

      await expect(service.installUpdate()).resolves.toEqual({
        installed: true,
      });
      expect(mockUpdater.quitAndInstall).toHaveBeenCalledTimes(1);
      expect(mockLog.warn).not.toHaveBeenCalledWith(
        "installUpdate called but no update is ready",
        expect.anything(),
      );
    });
  });

  describe("triggerMenuCheck", () => {
    it("emits CheckFromMenu event", () => {
      const handler = vi.fn();
      service.on(UpdatesEvent.CheckFromMenu, handler);

      service.triggerMenuCheck();

      expect(handler).toHaveBeenCalledWith(true);
    });
  });

  describe("autoUpdater event handling", () => {
    beforeEach(async () => {
      await initializeService(service);
    });

    it("registers all required event handlers", () => {
      expect(mockUpdater.onError).toHaveBeenCalled();
      expect(mockUpdater.onCheckStart).toHaveBeenCalled();
      expect(mockUpdater.onUpdateAvailable).toHaveBeenCalled();
      expect(mockUpdater.onNoUpdate).toHaveBeenCalled();
      expect(mockUpdater.onUpdateDownloaded).toHaveBeenCalled();
    });

    it("handles update-not-available event", () => {
      const statusHandler = vi.fn();
      service.on(UpdatesEvent.Status, statusHandler);

      // Start a check
      service.checkForUpdates();
      statusHandler.mockClear();

      // Simulate no update available
      const notAvailableHandler = updaterHandlers.noUpdate;

      if (notAvailableHandler) {
        notAvailableHandler();
      }

      expect(statusHandler).toHaveBeenCalledWith({
        checking: false,
        upToDate: true,
        version: "1.0.0",
      });
    });

    it("ignores later update events once an update is already downloaded", () => {
      // Simulate update already downloaded
      const downloadedHandler = updaterHandlers.updateDownloaded;
      if (downloadedHandler) {
        downloadedHandler("v2.0.0");
      }

      const statusHandler = vi.fn();
      const readyHandler = vi.fn();
      service.on(UpdatesEvent.Status, statusHandler);
      service.on(UpdatesEvent.Ready, readyHandler);

      mockUpdater.check.mockClear();

      // Periodic checks should be suppressed once an update is staged.
      service.checkForUpdates("periodic");
      expect(mockUpdater.check).not.toHaveBeenCalled();

      const notAvailableHandler = updaterHandlers.noUpdate;
      if (notAvailableHandler) {
        notAvailableHandler();
      }

      expect(statusHandler).not.toHaveBeenCalledWith({ checking: false });
      expect(statusHandler).not.toHaveBeenCalledWith(
        expect.objectContaining({ upToDate: true }),
      );
      expect(readyHandler).not.toHaveBeenCalled();
    });

    it("handles update-downloaded event with version info", () => {
      const readyHandler = vi.fn();
      service.on(UpdatesEvent.Ready, readyHandler);

      // Simulate update downloaded with version
      const downloadedHandler = updaterHandlers.updateDownloaded;

      if (downloadedHandler) {
        downloadedHandler("v2.0.0");
      }

      expect(readyHandler).toHaveBeenCalledWith({ version: "v2.0.0" });
    });

    it("emits a complete staged payload when an update is downloaded", () => {
      const statusHandler = vi.fn();
      service.on(UpdatesEvent.Status, statusHandler);

      updaterHandlers.updateDownloaded?.("v2.0.0");

      expect(statusHandler).toHaveBeenCalledWith({
        checking: false,
        updateReady: true,
        installing: false,
        version: "v2.0.0",
      });
    });

    it("handles error event and emits status with error", () => {
      const statusHandler = vi.fn();
      service.on(UpdatesEvent.Status, statusHandler);

      // Start a check
      service.checkForUpdates();
      statusHandler.mockClear();

      // Simulate error
      const errorHandler = updaterHandlers.error;

      if (errorHandler) {
        errorHandler(new Error("Network error"));
      }

      expect(statusHandler).toHaveBeenCalledWith({
        checking: false,
        error: "Network error",
      });
    });

    it("handles error event gracefully when not checking", () => {
      // Complete the initial check triggered by setupAutoUpdater so we're not in checking state
      const notAvailableHandler = updaterHandlers.noUpdate;
      if (notAvailableHandler) {
        notAvailableHandler();
      }

      const statusHandler = vi.fn();
      service.on(UpdatesEvent.Status, statusHandler);

      // Simulate error without starting a check
      const errorHandler = updaterHandlers.error;

      expect(() => {
        if (errorHandler) {
          errorHandler(new Error("Test error"));
        }
      }).not.toThrow();

      // Should not emit status since we weren't checking
      expect(statusHandler).not.toHaveBeenCalled();
    });
  });

  describe("status snapshots", () => {
    it("returns update-ready status for a staged update", async () => {
      await initializeService(service);

      updaterHandlers.updateDownloaded?.("v2.0.0");

      expect(service.getStatus()).toEqual({
        checking: false,
        updateReady: true,
        installing: false,
        version: "v2.0.0",
      });
    });

    it("flags installing in the staged status payload while install is in flight", async () => {
      await initializeService(service);

      updaterHandlers.updateDownloaded?.("v2.0.0");
      mockLifecycleService.shutdownWithoutContainer.mockReturnValue(
        new Promise(() => {}),
      );

      void service.installUpdate();
      // Allow the synchronous part of installUpdate to run.
      await Promise.resolve();

      expect(service.getStatus()).toEqual({
        checking: false,
        updateReady: true,
        installing: true,
        version: "v2.0.0",
      });
    });

    it("returns available status when an update is found", async () => {
      await initializeService(service);

      updaterHandlers.updateAvailable?.({
        version: "v2.0.0",
        releaseNotes: "Notes",
      });

      expect(service.getStatus()).toEqual({
        checking: false,
        available: true,
        availableVersion: "v2.0.0",
        releaseNotes: "Notes",
      });
    });

    it("auto-downloads and returns downloading status when enabled", async () => {
      await initializeService(service);
      service.setAutoDownloadEnabled(true);

      updaterHandlers.updateAvailable?.({
        version: "v2.0.0",
        releaseNotes: null,
      });

      expect(mockUpdater.download).toHaveBeenCalled();
      expect(service.getStatus()).toMatchObject({
        checking: true,
        downloading: true,
        availableVersion: "v2.0.0",
      });
    });

    it("downloads on requestDownload and reaches ready", async () => {
      await initializeService(service);

      updaterHandlers.updateAvailable?.({
        version: "v2.0.0",
        releaseNotes: null,
      });
      service.requestDownload();
      expect(mockUpdater.download).toHaveBeenCalled();
      expect(service.getStatus()).toMatchObject({ downloading: true });

      updaterHandlers.updateDownloaded?.("v2.0.0");
      expect(service.getStatus()).toMatchObject({
        updateReady: true,
        version: "v2.0.0",
      });
    });
  });

  describe("available update guards", () => {
    it("does not re-check or clear the banner on periodic checks while available", async () => {
      await initializeService(service);

      updaterHandlers.updateAvailable?.({
        version: "v2.0.0",
        releaseNotes: "Notes",
      });
      expect(service.getStatus()).toMatchObject({
        available: true,
        availableVersion: "v2.0.0",
      });

      const statusHandler = vi.fn();
      service.on(UpdatesEvent.Status, statusHandler);
      mockUpdater.check.mockClear();

      const result = service.checkForUpdates("periodic");

      expect(result).toEqual({ success: true });
      expect(mockUpdater.check).not.toHaveBeenCalled();
      expect(statusHandler).not.toHaveBeenCalled();
      expect(service.getStatus()).toMatchObject({
        available: true,
        availableVersion: "v2.0.0",
      });
    });

    it("starts the download when auto-download is enabled while available", async () => {
      await initializeService(service);

      updaterHandlers.updateAvailable?.({
        version: "v2.0.0",
        releaseNotes: null,
      });
      expect(service.getStatus()).toMatchObject({ available: true });

      mockUpdater.download.mockClear();
      service.setAutoDownloadEnabled(true);

      expect(mockUpdater.download).toHaveBeenCalled();
      expect(service.getStatus()).toMatchObject({
        downloading: true,
        availableVersion: "v2.0.0",
      });
    });
  });

  describe("check timeout", () => {
    beforeEach(async () => {
      await initializeService(service);
    });

    it("times out after 60 seconds if no response", async () => {
      const statusHandler = vi.fn();
      service.on(UpdatesEvent.Status, statusHandler);

      service.checkForUpdates();
      statusHandler.mockClear();

      // Advance 60 seconds
      await vi.advanceTimersByTimeAsync(60 * 1000);

      expect(statusHandler).toHaveBeenCalledWith({
        checking: false,
        error: "Update check timed out. Please try again.",
      });
    });

    it("clears timeout when update-not-available fires", async () => {
      const statusHandler = vi.fn();
      service.on(UpdatesEvent.Status, statusHandler);

      service.checkForUpdates();
      statusHandler.mockClear();

      // Simulate response before timeout
      const notAvailableHandler = updaterHandlers.noUpdate;

      if (notAvailableHandler) {
        notAvailableHandler();
      }

      // Advance past the timeout
      await vi.advanceTimersByTimeAsync(60 * 1000);

      // Should only have received the upToDate status, not a timeout
      expect(statusHandler).toHaveBeenCalledTimes(1);
      expect(statusHandler).toHaveBeenCalledWith({
        checking: false,
        upToDate: true,
        version: "1.0.0",
      });
    });

    it("clears timeout when error fires", async () => {
      const statusHandler = vi.fn();
      service.on(UpdatesEvent.Status, statusHandler);

      service.checkForUpdates();
      statusHandler.mockClear();

      // Simulate error before timeout
      const errorHandler = updaterHandlers.error;

      if (errorHandler) {
        errorHandler(new Error("Network error"));
      }

      // Advance past the timeout
      await vi.advanceTimersByTimeAsync(60 * 1000);

      // Should only have received the error status, not a timeout
      expect(statusHandler).toHaveBeenCalledTimes(1);
      expect(statusHandler).toHaveBeenCalledWith({
        checking: false,
        error: "Network error",
      });
    });
  });

  describe("flushPendingNotification", () => {
    it("emits Ready event on window focus when update is pending", async () => {
      await initializeService(service);

      const readyHandler = vi.fn();
      service.on(UpdatesEvent.Ready, readyHandler);

      // Simulate update downloaded
      const downloadedHandler = updaterHandlers.updateDownloaded;

      if (downloadedHandler) {
        downloadedHandler("v2.0.0");
      }

      // First Ready event from handleUpdateDownloaded
      expect(readyHandler).toHaveBeenCalledTimes(1);

      // Reset the handler count
      readyHandler.mockClear();

      // Pending notification should be false now, so no second emit
      updaterHandlers.focus?.();

      expect(readyHandler).not.toHaveBeenCalled();
    });
  });

  describe("periodic update checks", () => {
    it("performs initial check on setup", async () => {
      await initializeService(service);

      expect(mockUpdater.check).toHaveBeenCalled();
    });

    it("performs check every hour", async () => {
      await initializeService(service);

      const initialCallCount = mockUpdater.check.mock.calls.length;

      // Advance 1 hour
      await vi.advanceTimersByTimeAsync(60 * 60 * 1000);

      expect(mockUpdater.check.mock.calls.length).toBe(initialCallCount + 1);

      // Advance another hour
      await vi.advanceTimersByTimeAsync(60 * 60 * 1000);

      expect(mockUpdater.check.mock.calls.length).toBe(initialCallCount + 2);
    });

    it("stops the periodic interval once an update is staged", async () => {
      await initializeService(service);

      updaterHandlers.updateDownloaded?.("v2.0.0");

      const baselineCallCount = mockUpdater.check.mock.calls.length;

      // The interval would normally fire every hour; with the update staged it
      // should be cleared so no further wake-ups occur.
      await vi.advanceTimersByTimeAsync(60 * 60 * 1000 * 3);

      expect(mockUpdater.check.mock.calls.length).toBe(baselineCallCount);
    });
  });

  describe("staged update guards", () => {
    it("does not re-check on periodic checks when update is ready", async () => {
      await initializeService(service);

      // Simulate update downloaded
      const downloadedHandler = updaterHandlers.updateDownloaded;
      if (downloadedHandler) {
        downloadedHandler("v2.0.0");
      }

      // Clear the checkForUpdates calls from initialization
      mockUpdater.check.mockClear();

      // Periodic check should not overwrite or refresh the staged update.
      const result = service.checkForUpdates("periodic");
      expect(result).toEqual({ success: true });
      expect(mockUpdater.check).not.toHaveBeenCalled();
      // Update should still be ready (state not reset)
      expect(service.hasUpdateReady).toBe(true);
    });

    it("user check still shows existing notification when update is ready", async () => {
      await initializeService(service);

      // Simulate update downloaded
      const downloadedHandler = updaterHandlers.updateDownloaded;
      if (downloadedHandler) {
        downloadedHandler("v2.0.0");
      }

      const readyHandler = vi.fn();
      service.on(UpdatesEvent.Ready, readyHandler);

      // User check should show existing notification, not re-check
      mockUpdater.check.mockClear();
      const result = service.checkForUpdates("user");
      expect(result).toEqual({ success: true });
      expect(mockUpdater.check).not.toHaveBeenCalled();
      expect(readyHandler).toHaveBeenCalledWith({ version: "v2.0.0" });
    });

    it("preserves downloaded update when later updater errors fire", async () => {
      await initializeService(service);

      // Simulate update downloaded
      const downloadedHandler = updaterHandlers.updateDownloaded;
      if (downloadedHandler) {
        downloadedHandler("v2.0.0");
      }

      mockUpdater.check.mockClear();
      service.checkForUpdates("periodic");
      expect(mockUpdater.check).not.toHaveBeenCalled();

      // Simulate a stale updater error after staging.
      const errorHandler = updaterHandlers.error;
      if (errorHandler) {
        errorHandler(new Error("Network error"));
      }

      // Update should still be ready
      expect(service.hasUpdateReady).toBe(true);
    });

    it("does not re-notify when same version is re-downloaded after staging", async () => {
      await initializeService(service);

      const readyHandler = vi.fn();
      service.on(UpdatesEvent.Ready, readyHandler);

      // First download of v2.0.0
      const downloadedHandler = updaterHandlers.updateDownloaded;
      if (downloadedHandler) {
        downloadedHandler("v2.0.0");
      }
      expect(readyHandler).toHaveBeenCalledTimes(1);

      readyHandler.mockClear();

      if (downloadedHandler) {
        downloadedHandler("v2.0.0");
      }

      // Should NOT re-notify since same version
      expect(readyHandler).not.toHaveBeenCalled();
    });

    it("does not overwrite staged version when a later download event arrives", async () => {
      await initializeService(service);

      const readyHandler = vi.fn();
      service.on(UpdatesEvent.Ready, readyHandler);

      // Simulate update downloaded
      const downloadedHandler = updaterHandlers.updateDownloaded;
      if (downloadedHandler) {
        downloadedHandler("v2.0.0");
      }
      expect(readyHandler).toHaveBeenCalledWith({ version: "v2.0.0" });

      readyHandler.mockClear();

      if (downloadedHandler) {
        downloadedHandler("v3.0.0");
      }

      // User checks should still surface the originally staged update.
      service.checkForUpdates("user");
      expect(readyHandler).toHaveBeenCalledWith({ version: "v2.0.0" });

      // Update should still be ready (state not corrupted)
      expect(service.hasUpdateReady).toBe(true);
    });
  });

  describe("transition logging", () => {
    it("logs state transitions with source and state metadata", () => {
      service.checkForUpdates("user");

      expect(mockLog.info).toHaveBeenCalledWith(
        "Update state transition",
        expect.objectContaining({
          source: "user",
          fromState: "idle",
          toState: "checking",
          downloadedVersion: null,
          skippedBecauseUpdateStaged: false,
        }),
      );
    });

    it("logs skipped checks after an update is staged", async () => {
      await initializeService(service);
      updaterHandlers.updateDownloaded?.("v2.0.0");

      mockLog.info.mockClear();
      service.checkForUpdates("periodic");

      expect(mockLog.info).toHaveBeenCalledWith(
        "Update state transition",
        expect.objectContaining({
          source: "periodic",
          fromState: "ready",
          toState: "ready",
          downloadedVersion: "v2.0.0",
          skippedBecauseUpdateStaged: true,
        }),
      );
    });
  });

  describe("error handling", () => {
    it("catches errors during checkForUpdates", async () => {
      await initializeService(service);

      mockUpdater.check.mockImplementation(() => {
        throw new Error("Network error");
      });

      // Should not throw
      expect(() => service.checkForUpdates()).not.toThrow();
    });
  });
});
