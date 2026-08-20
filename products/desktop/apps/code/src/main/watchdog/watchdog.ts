import {
  formatBytes,
  loadWatchdogConfig,
  type WatchdogConfig,
} from "@main/watchdog/config";
import { writeReport } from "@main/watchdog/report";
import { collectSample } from "@main/watchdog/sampler";
import { WatchdogStore } from "@main/watchdog/store";
import type {
  MemorySample,
  WatchdogReport,
  WatchdogTrigger,
} from "@main/watchdog/types";
import type { ScopedLogger } from "@posthog/di/logger";
import type { AppProcessMetric } from "@posthog/platform/app-metrics";

const BREADCRUMB_PROCESS_LIMIT = 10;

export interface MemoryWatchdogDeps {
  /** Directory the watchdog owns, supplied by the host. */
  diagnosticsDirectory: string;
  getAppMetrics: () => AppProcessMetric[];
  /** Version/platform metadata recorded in every report. */
  appInfo: () => Record<string, unknown>;
  logger: ScopedLogger;
  /** Writes a renderer heap snapshot into `directory`, returns the filename. */
  takeRendererHeapSnapshot?: (directory: string) => Promise<string>;
  /** Called after a report lands, for analytics. Must not throw. */
  onReport?: (report: WatchdogReport, sample: MemorySample | null) => void;
  env?: NodeJS.ProcessEnv;
  totalMemoryBytes?: number;
}

export interface WatchdogStatus {
  enabled: boolean;
  running: boolean;
  config: WatchdogConfig;
  reportsDirectory: string;
  latestSample: MemorySample | null;
  consecutiveBreaches: number;
}

/**
 * Samples memory across the whole process tree and captures a report when the
 * app balloons or dies.
 *
 * Deliberately not an Inversify service: it has to run before the container is
 * ready, keep running while the app is tearing itself down, and reach Electron
 * surfaces (crash events, app metrics) that only the host can provide. The host
 * passes those in; everything here is plain and testable.
 */
export class MemoryWatchdog {
  readonly config: WatchdogConfig;

  private readonly store: WatchdogStore;
  private readonly log: ScopedLogger;
  private timer: NodeJS.Timeout | null = null;
  private history: MemorySample[] = [];
  private latestSample: MemorySample | null = null;
  private consecutiveBreaches = 0;
  private lastCaptureAt = 0;
  private sampling = false;
  private capturing = false;

  constructor(private readonly deps: MemoryWatchdogDeps) {
    const { config, warnings } = loadWatchdogConfig(
      deps.env,
      deps.totalMemoryBytes,
    );
    this.config = config;
    this.log = deps.logger;
    this.store = new WatchdogStore(deps.diagnosticsDirectory);

    for (const warning of warnings) {
      this.log.warn("Ignoring non-numeric watchdog setting", warning);
    }
  }

  get reportsDirectory(): string {
    return this.store.reportsDirectory;
  }

  getStatus(): WatchdogStatus {
    return {
      enabled: this.config.enabled,
      running: this.timer !== null,
      config: this.config,
      reportsDirectory: this.store.reportsDirectory,
      latestSample: this.latestSample,
      consecutiveBreaches: this.consecutiveBreaches,
    };
  }

  async start(): Promise<void> {
    if (!this.config.enabled || this.timer) {
      return;
    }

    try {
      await this.store.ensureDirectories();
      await this.reportUncleanShutdown();
      await this.store.writeSessionSentinel({
        pid: process.pid,
        version: String(this.deps.appInfo().version ?? "unknown"),
        platform: `${process.platform}-${process.arch}`,
        startedAt: new Date().toISOString(),
      });
    } catch (error) {
      this.log.error("Failed to initialise", error);
    }

    this.log.info("Watching memory", {
      intervalSeconds: Math.round(this.config.sampleIntervalMs / 1000),
      threshold: formatBytes(this.config.thresholdBytes),
      heapSnapshots: this.config.heapSnapshots,
    });

    void this.tick();
    this.timer = setInterval(
      () => void this.tick(),
      this.config.sampleIntervalMs,
    );
  }

  stop(): void {
    if (this.timer) {
      clearInterval(this.timer);
      this.timer = null;
    }
  }

  /**
   * Called once a shutdown has actually succeeded, so the next launch does not
   * report a crash. Synchronous because the paths that reach it are exit
   * handlers — `app.exit()` and `process.exit()` do not wait for a promise.
   */
  markCleanShutdown(): void {
    this.stop();
    this.store.clearSessionSentinelSync();
  }

  async capture(
    trigger: WatchdogTrigger,
    detail?: string,
    context?: Record<string, unknown>,
  ): Promise<WatchdogReport | null> {
    // The crash handlers and the Developer menu call this directly whether or
    // not the watchdog is on, so this is where an opted-out install stops
    // writing diagnostics — not just `start()`.
    if (!this.config.enabled) {
      this.log.debug("Watchdog disabled, not capturing", { trigger });
      return null;
    }

    // Crashes arrive in bursts — a renderer dies, then its children do — and a
    // heap snapshot is slow enough that reentrancy would pile up.
    if (this.capturing) {
      this.log.warn("Capture already in progress, skipping", { trigger });
      return null;
    }

    this.capturing = true;
    try {
      const sample =
        trigger === "unclean-shutdown"
          ? this.latestSample
          : await collectSample(
              this.deps.getAppMetrics,
              this.config.fullCommandLines,
            );

      const report = await writeReport({
        store: this.store,
        config: this.config,
        trigger,
        detail,
        sample,
        history: this.history,
        context,
        appInfo: this.deps.appInfo(),
        takeRendererHeapSnapshot: this.deps.takeRendererHeapSnapshot,
        onError: (message, error) => this.log.error(message, error),
      });

      this.lastCaptureAt = Date.now();
      this.log.warn("Captured memory report", {
        trigger,
        directory: report.directory,
        totalRss: sample ? formatBytes(sample.totalRssBytes) : "unknown",
      });

      const pruned = await this.store.pruneReports(this.config.maxReports);
      if (pruned.length > 0) {
        this.log.info("Pruned old memory reports", { count: pruned.length });
      }

      this.deps.onReport?.(report, sample);
      return report;
    } catch (error) {
      this.log.error("Failed to capture report", { trigger, error });
      return null;
    } finally {
      this.capturing = false;
    }
  }

  private async tick(): Promise<void> {
    // `ps` is a subprocess; under load a tick can outlast the interval.
    if (this.sampling) return;
    this.sampling = true;

    try {
      const sample = await collectSample(
        this.deps.getAppMetrics,
        this.config.fullCommandLines,
      );
      this.latestSample = sample;

      this.history.push(sample);
      if (this.history.length > this.config.ringSize) {
        this.history = this.history.slice(-this.config.ringSize);
      }

      await this.store.appendBreadcrumb(
        toBreadcrumb(sample),
        this.config.breadcrumbMaxBytes,
      );

      if (sample.totalRssBytes < this.config.thresholdBytes) {
        this.consecutiveBreaches = 0;
        return;
      }

      this.consecutiveBreaches += 1;
      if (this.consecutiveBreaches < this.config.sustainedSamples) {
        return;
      }

      // A spike that stays up is one report, not one per sample.
      if (Date.now() - this.lastCaptureAt < this.config.cooldownMs) {
        return;
      }

      await this.capture(
        "threshold",
        `${formatBytes(sample.totalRssBytes)} resident across ${sample.processCount} processes, threshold ${formatBytes(this.config.thresholdBytes)}`,
      );
    } catch (error) {
      this.log.error("Sample failed", error);
    } finally {
      this.sampling = false;
    }
  }

  /**
   * A sentinel left by the previous run means it never reached a shutdown path:
   * the OOM killer, a force quit, or a hard crash. The breadcrumbs it left
   * behind are the only evidence, so promote them into a report.
   */
  private async reportUncleanShutdown(): Promise<void> {
    const stale = await this.store.takeStaleSessionSentinel();
    if (!stale) return;

    this.log.warn("Previous session exited without shutting down", stale);
    await this.capture(
      "unclean-shutdown",
      "Previous session did not reach a shutdown handler; see breadcrumbs for the run-up",
      { previousSession: stale },
    );
  }
}

/**
 * A trimmed sample. Breadcrumbs are written on every tick and have to stay
 * small enough that keeping months of them costs nothing.
 */
function toBreadcrumb(sample: MemorySample) {
  return {
    at: sample.at,
    totalRssBytes: sample.totalRssBytes,
    electronRssBytes: sample.electronRssBytes,
    descendantRssBytes: sample.descendantRssBytes,
    processCount: sample.processCount,
    mainRssBytes: sample.main.rssBytes,
    mainHeapUsedBytes: sample.main.heapUsedBytes,
    systemFreeBytes: sample.system.freeBytes,
    top: sample.processes.slice(0, BREADCRUMB_PROCESS_LIMIT).map((proc) => ({
      pid: proc.pid,
      label: proc.label,
      rssBytes: proc.rssBytes,
    })),
  };
}
