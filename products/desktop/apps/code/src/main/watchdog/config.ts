import os from "node:os";

const MB = 1024 * 1024;
const GB = 1024 * MB;

// The watchdog is only interesting when the app is genuinely large, so the
// default threshold scales with the machine rather than being a fixed number.
// A 16GB laptop trips at 8GB; a 128GB desktop trips at 24GB.
const THRESHOLD_RATIO = 0.5;
const THRESHOLD_MIN_BYTES = 2 * GB;
const THRESHOLD_MAX_BYTES = 24 * GB;

export interface WatchdogConfig {
  enabled: boolean;
  /** How often the sampler runs. */
  sampleIntervalMs: number;
  /** Total resident memory across the process tree that counts as a spike. */
  thresholdBytes: number;
  /** Consecutive samples above the threshold before we capture. */
  sustainedSamples: number;
  /** Minimum gap between threshold captures so a plateau writes one report. */
  cooldownMs: number;
  /** Samples kept in memory, and copied into each report. */
  ringSize: number;
  /**
   * Report directories kept on disk before the oldest are pruned. Deliberately
   * small: these sit in the log folder and can hold heap snapshots.
   */
  maxReports: number;
  /**
   * Whether to write V8 heap snapshots. Off by default: a snapshot is roughly
   * as large as the heap and freezes the process while it is written.
   */
  heapSnapshots: boolean;
  /** Size the breadcrumb log may reach before it rotates. */
  breadcrumbMaxBytes: number;
}

export interface ConfigWarning {
  variable: string;
  value: string;
}

export interface LoadedWatchdogConfig {
  config: WatchdogConfig;
  /** Env vars that were set but unparseable, for the caller to log. */
  warnings: ConfigWarning[];
}

function readFlag(name: string, env: NodeJS.ProcessEnv): boolean {
  const raw = env[name];
  if (!raw) return false;
  return raw !== "0" && raw.toLowerCase() !== "false";
}

function defaultThresholdBytes(totalMemoryBytes: number): number {
  const scaled = totalMemoryBytes * THRESHOLD_RATIO;
  return Math.min(Math.max(scaled, THRESHOLD_MIN_BYTES), THRESHOLD_MAX_BYTES);
}

export function loadWatchdogConfig(
  env: NodeJS.ProcessEnv = process.env,
  totalMemoryBytes: number = os.totalmem(),
): LoadedWatchdogConfig {
  const warnings: ConfigWarning[] = [];

  const readInt = (
    name: string,
    fallback: number,
    min: number,
    max: number,
  ): number => {
    const raw = env[name];
    if (!raw) return fallback;

    const parsed = Number.parseInt(raw, 10);
    if (!Number.isFinite(parsed)) {
      warnings.push({ variable: name, value: raw });
      return fallback;
    }

    return Math.min(Math.max(parsed, min), max);
  };

  const thresholdMb = readInt(
    "POSTHOG_CODE_WATCHDOG_THRESHOLD_MB",
    Math.round(defaultThresholdBytes(totalMemoryBytes) / MB),
    256,
    1024 * 1024,
  );

  return {
    warnings,
    config: {
      enabled: !readFlag("POSTHOG_CODE_WATCHDOG_DISABLE", env),
      sampleIntervalMs: readInt(
        "POSTHOG_CODE_WATCHDOG_INTERVAL_MS",
        15_000,
        1_000,
        600_000,
      ),
      thresholdBytes: thresholdMb * MB,
      sustainedSamples: readInt(
        "POSTHOG_CODE_WATCHDOG_SUSTAINED_SAMPLES",
        3,
        1,
        100,
      ),
      cooldownMs: readInt(
        "POSTHOG_CODE_WATCHDOG_COOLDOWN_MS",
        10 * 60_000,
        0,
        24 * 60 * 60_000,
      ),
      ringSize: readInt("POSTHOG_CODE_WATCHDOG_RING_SIZE", 120, 10, 5_000),
      maxReports: readInt("POSTHOG_CODE_WATCHDOG_MAX_REPORTS", 3, 1, 200),
      heapSnapshots: readFlag("POSTHOG_CODE_WATCHDOG_HEAP_SNAPSHOTS", env),
      breadcrumbMaxBytes:
        readInt("POSTHOG_CODE_WATCHDOG_BREADCRUMB_MB", 16, 1, 1024) * MB,
    },
  };
}

export function formatBytes(bytes: number): string {
  if (bytes < MB) return `${Math.round(bytes / 1024)}KB`;
  if (bytes < GB) return `${Math.round(bytes / MB)}MB`;
  return `${(bytes / GB).toFixed(2)}GB`;
}
