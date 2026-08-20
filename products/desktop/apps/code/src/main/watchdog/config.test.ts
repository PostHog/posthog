import { formatBytes, loadWatchdogConfig } from "@main/watchdog/config";
import { describe, expect, it } from "vitest";

const MB = 1024 * 1024;
const GB = 1024 * MB;

describe("loadWatchdogConfig", () => {
  it("is enabled with heap snapshots off by default", () => {
    const { config } = loadWatchdogConfig({}, 16 * GB);

    expect(config.enabled).toBe(true);
    expect(config.heapSnapshots).toBe(false);
  });

  it("keeps only the last three reports by default", () => {
    expect(loadWatchdogConfig({}, 16 * GB).config.maxReports).toBe(3);
  });

  it.each([
    ["scales to half of system memory", 32 * GB, 16 * GB],
    ["clamps on very large machines", 512 * GB, 24 * GB],
    ["clamps on very small machines", 2 * GB, 2 * GB],
  ])("default threshold %s", (_name, totalMemory, expected) => {
    expect(loadWatchdogConfig({}, totalMemory).config.thresholdBytes).toBe(
      expected,
    );
  });

  it("lets the threshold be overridden in megabytes", () => {
    const { config } = loadWatchdogConfig(
      { POSTHOG_CODE_WATCHDOG_THRESHOLD_MB: "4096" },
      16 * GB,
    );

    expect(config.thresholdBytes).toBe(4096 * MB);
  });

  it("reports an unparseable override and falls back to the default", () => {
    const { config, warnings } = loadWatchdogConfig(
      { POSTHOG_CODE_WATCHDOG_THRESHOLD_MB: "lots" },
      16 * GB,
    );

    expect(config.thresholdBytes).toBe(8 * GB);
    expect(warnings).toEqual([
      { variable: "POSTHOG_CODE_WATCHDOG_THRESHOLD_MB", value: "lots" },
    ]);
  });

  it("keeps the sample interval within a sane range", () => {
    const { config } = loadWatchdogConfig(
      { POSTHOG_CODE_WATCHDOG_INTERVAL_MS: "5" },
      16 * GB,
    );

    expect(config.sampleIntervalMs).toBe(1_000);
  });

  it("treats an explicit 0 or false as not set", () => {
    const { config } = loadWatchdogConfig(
      {
        POSTHOG_CODE_WATCHDOG_DISABLE: "0",
        POSTHOG_CODE_WATCHDOG_HEAP_SNAPSHOTS: "false",
      },
      16 * GB,
    );

    expect(config.enabled).toBe(true);
    expect(config.heapSnapshots).toBe(false);
  });

  it("disables the watchdog when the flag is set", () => {
    const { config } = loadWatchdogConfig(
      { POSTHOG_CODE_WATCHDOG_DISABLE: "1" },
      16 * GB,
    );

    expect(config.enabled).toBe(false);
  });
});

describe("formatBytes", () => {
  it.each([
    [512 * 1024, "512KB"],
    [700 * MB, "700MB"],
    [3.5 * GB, "3.50GB"],
  ])("formats %i as %s", (bytes, expected) => {
    expect(formatBytes(bytes)).toBe(expected);
  });
});
