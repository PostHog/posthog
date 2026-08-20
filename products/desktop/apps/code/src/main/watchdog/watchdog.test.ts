import {
  existsSync,
  mkdtempSync,
  readdirSync,
  readFileSync,
  rmSync,
} from "node:fs";
import os from "node:os";
import path from "node:path";
import v8 from "node:v8";
import { WatchdogStore } from "@main/watchdog/store";
import type { MemorySample } from "@main/watchdog/types";
import {
  MemoryWatchdog,
  type MemoryWatchdogDeps,
} from "@main/watchdog/watchdog";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const { collectSample } = vi.hoisted(() => ({ collectSample: vi.fn() }));
vi.mock("@main/watchdog/sampler", () => ({ collectSample }));

const GB = 1024 * 1024 * 1024;

function sampleWithRss(totalRssBytes: number): MemorySample {
  return {
    at: new Date().toISOString(),
    totalRssBytes,
    electronRssBytes: totalRssBytes,
    descendantRssBytes: 0,
    processCount: 3,
    processTreeAvailable: true,
    main: {
      pid: 1,
      rssBytes: 1,
      heapUsedBytes: 1,
      heapTotalBytes: 1,
      externalBytes: 0,
      arrayBuffersBytes: 0,
    },
    system: { totalBytes: 16 * GB, freeBytes: 1 * GB, loadAverage: [0, 0, 0] },
    processes: [],
  };
}

let directory: string;
const logger = { debug: vi.fn(), info: vi.fn(), warn: vi.fn(), error: vi.fn() };

function createWatchdog(
  env: NodeJS.ProcessEnv = {},
  deps: Partial<MemoryWatchdogDeps> = {},
) {
  return new MemoryWatchdog({
    diagnosticsDirectory: directory,
    getAppMetrics: () => [],
    appInfo: () => ({ version: "0.0.0-test" }),
    logger,
    env: {
      POSTHOG_CODE_WATCHDOG_THRESHOLD_MB: "1024",
      POSTHOG_CODE_WATCHDOG_INTERVAL_MS: "1000",
      ...env,
    },
    totalMemoryBytes: 16 * GB,
    ...deps,
  });
}

/** Drives the private sampling loop the way the interval would. */
async function tick(watchdog: MemoryWatchdog, times = 1): Promise<void> {
  for (let i = 0; i < times; i++) {
    await (watchdog as unknown as { tick: () => Promise<void> }).tick();
  }
}

beforeEach(() => {
  directory = mkdtempSync(path.join(os.tmpdir(), "watchdog-test-"));
  collectSample.mockReset();
  logger.warn.mockReset();
});

afterEach(() => {
  vi.restoreAllMocks();
  rmSync(directory, { recursive: true, force: true });
});

describe("MemoryWatchdog", () => {
  it("does not capture until the threshold is breached for enough samples", async () => {
    collectSample.mockResolvedValue(sampleWithRss(2 * GB));
    const watchdog = createWatchdog({
      POSTHOG_CODE_WATCHDOG_SUSTAINED_SAMPLES: "3",
    });

    await tick(watchdog, 2);
    expect(await listReports(watchdog)).toHaveLength(0);

    await tick(watchdog);
    expect(await listReports(watchdog)).toHaveLength(1);
  });

  it("resets the breach count when memory drops back down", async () => {
    const watchdog = createWatchdog({
      POSTHOG_CODE_WATCHDOG_SUSTAINED_SAMPLES: "3",
    });

    collectSample.mockResolvedValue(sampleWithRss(2 * GB));
    await tick(watchdog, 2);
    collectSample.mockResolvedValue(sampleWithRss(0.5 * GB));
    await tick(watchdog);
    collectSample.mockResolvedValue(sampleWithRss(2 * GB));
    await tick(watchdog, 2);

    expect(await listReports(watchdog)).toHaveLength(0);
  });

  it("writes one report per plateau, not one per sample", async () => {
    collectSample.mockResolvedValue(sampleWithRss(2 * GB));
    const watchdog = createWatchdog({
      POSTHOG_CODE_WATCHDOG_SUSTAINED_SAMPLES: "1",
      POSTHOG_CODE_WATCHDOG_COOLDOWN_MS: "600000",
    });

    await tick(watchdog, 5);

    expect(await listReports(watchdog)).toHaveLength(1);
  });

  it("does not let a non-threshold capture suppress a later threshold report", async () => {
    collectSample.mockResolvedValue(sampleWithRss(2 * GB));
    const watchdog = createWatchdog({
      POSTHOG_CODE_WATCHDOG_SUSTAINED_SAMPLES: "1",
      POSTHOG_CODE_WATCHDOG_COOLDOWN_MS: "600000",
    });

    // A manual snapshot must not start the threshold cooldown; the cooldown
    // only dedupes a sustained spike, not unrelated captures.
    await watchdog.capture("manual", "manual snapshot");
    await tick(watchdog);

    const triggers = (await listReports(watchdog)).map(
      (report) => report.trigger,
    );
    expect(triggers).toContain("threshold");
  });

  it("records the samples leading up to the spike", async () => {
    collectSample.mockResolvedValue(sampleWithRss(2 * GB));
    const watchdog = createWatchdog({
      POSTHOG_CODE_WATCHDOG_SUSTAINED_SAMPLES: "3",
    });

    await tick(watchdog, 3);

    const [report] = await listReports(watchdog);
    const contents = JSON.parse(
      readFileSync(path.join(report.directory, "report.json"), "utf-8"),
    );
    expect(contents.history).toHaveLength(3);
    expect(contents.trigger).toBe("threshold");
  });

  it("appends a breadcrumb on every sample so a SIGKILL leaves a trail", async () => {
    collectSample.mockResolvedValue(sampleWithRss(0.1 * GB));
    const watchdog = createWatchdog();

    await tick(watchdog, 3);

    const lines = readFileSync(
      path.join(directory, "breadcrumbs.jsonl"),
      "utf-8",
    )
      .split("\n")
      .filter(Boolean);
    expect(lines).toHaveLength(3);
    expect(JSON.parse(lines[0]).totalRssBytes).toBe(0.1 * GB);
  });

  it("prunes report directories beyond the retention limit", async () => {
    collectSample.mockResolvedValue(sampleWithRss(2 * GB));
    const watchdog = createWatchdog({
      POSTHOG_CODE_WATCHDOG_MAX_REPORTS: "2",
    });

    for (let i = 0; i < 4; i++) {
      await watchdog.capture("manual", `capture ${i}`);
    }

    expect(await listReports(watchdog)).toHaveLength(2);
  });

  it("still reports a capture whose pruning failed", async () => {
    collectSample.mockResolvedValue(sampleWithRss(2 * GB));
    // `rm` can fail with EPERM or EBUSY. Pruning runs after the report is on
    // disk, so treating that as a failed capture would discard a report that
    // exists and skip the analytics for it.
    vi.spyOn(WatchdogStore.prototype, "pruneReports").mockRejectedValue(
      new Error("EBUSY"),
    );
    const onReport = vi.fn();
    const watchdog = createWatchdog({}, { onReport });

    const report = await watchdog.capture("manual", "cleanup will fail");

    expect(report).not.toBeNull();
    expect(onReport).toHaveBeenCalledOnce();
  });

  // Snapshots are heap-sized and can hang on a renderer too far gone to answer,
  // so the report has to be on disk before one starts.
  it("writes the report before it takes a heap snapshot", async () => {
    vi.spyOn(v8, "writeHeapSnapshot").mockReturnValue("main.heapsnapshot");
    collectSample.mockResolvedValue(sampleWithRss(2 * GB));

    let reportWasOnDisk = false;
    const watchdog = createWatchdog(
      { POSTHOG_CODE_WATCHDOG_HEAP_SNAPSHOTS: "1" },
      {
        takeRendererHeapSnapshot: async (reportDirectory: string) => {
          reportWasOnDisk = ["report.json", "summary.json"].every((file) =>
            existsSync(path.join(reportDirectory, file)),
          );
          return "renderer.heapsnapshot";
        },
      },
    );

    const report = await watchdog.capture("manual", "with snapshots");

    expect(reportWasOnDisk).toBe(true);
    expect(report?.files).toContain("renderer.heapsnapshot");
  });

  it("turns a leftover session sentinel into an unclean-shutdown report", async () => {
    collectSample.mockResolvedValue(sampleWithRss(0.1 * GB));
    const first = createWatchdog();
    await first.start();
    first.stop();

    // stop() without markCleanShutdown: what a force-killed quit leaves behind,
    // since before-quit stops sampling but only a completed shutdown clears the
    // sentinel.
    const second = createWatchdog();
    await second.start();
    second.stop();

    const triggers = (await listReports(second)).map(
      (report) => report.trigger,
    );
    expect(triggers).toContain("unclean-shutdown");
  });

  it("does not report an unclean shutdown after a clean quit", async () => {
    collectSample.mockResolvedValue(sampleWithRss(0.1 * GB));
    const first = createWatchdog();
    await first.start();
    first.markCleanShutdown();

    const second = createWatchdog();
    await second.start();
    second.stop();

    expect(await listReports(second)).toHaveLength(0);
  });

  it("stays out of the way entirely when disabled", async () => {
    const watchdog = createWatchdog({ POSTHOG_CODE_WATCHDOG_DISABLE: "1" });

    await watchdog.start();

    expect(watchdog.getStatus().running).toBe(false);
    expect(collectSample).not.toHaveBeenCalled();
  });

  // The host registers its crash handlers whether or not the watchdog is on, so
  // they are the path by which an opted-out install could still write to disk.
  it.each([
    "render-process-gone",
    "child-process-gone",
    "uncaught-exception",
    "manual",
  ] as const)(
    "writes nothing on a %s capture when disabled",
    async (trigger) => {
      collectSample.mockResolvedValue(sampleWithRss(2 * GB));
      const watchdog = createWatchdog({ POSTHOG_CODE_WATCHDOG_DISABLE: "1" });

      expect(await watchdog.capture(trigger, "should not be recorded")).toBe(
        null,
      );
      expect(await listReports(watchdog)).toHaveLength(0);
      expect(readdirSync(directory)).toEqual([]);
    },
  );
});

async function listReports(watchdog: MemoryWatchdog) {
  const { readdir, readFile } = await import("node:fs/promises");
  let entries: string[];
  try {
    entries = await readdir(watchdog.reportsDirectory);
  } catch {
    return [];
  }
  return Promise.all(
    entries.map(async (name) =>
      JSON.parse(
        await readFile(
          path.join(watchdog.reportsDirectory, name, "summary.json"),
          "utf-8",
        ),
      ),
    ),
  );
}
