import { mergeProcesses } from "@main/watchdog/sampler";
import type { AppProcessMetric } from "@posthog/platform/app-metrics";
import { describe, expect, it } from "vitest";

const METRICS: AppProcessMetric[] = [
  {
    pid: 500,
    type: "Browser",
    memory: { workingSetSize: 300_000 },
    cpu: { percentCPUUsage: 1 },
  },
  {
    pid: 501,
    type: "Tab",
    name: "PostHog",
    memory: { workingSetSize: 400_000 },
    cpu: { percentCPUUsage: 2 },
  },
];

const TREE = [
  { pid: 500, ppid: 1, rssBytes: 350_000_000, cpuPercent: 1.5, command: "app" },
  {
    pid: 501,
    ppid: 500,
    rssBytes: 410_000_000,
    cpuPercent: 2.5,
    command: "app --type=renderer",
  },
  {
    pid: 502,
    ppid: 500,
    rssBytes: 2_000_000_000,
    cpuPercent: 90,
    command: "node cli.js --task 42",
  },
];

describe("mergeProcesses", () => {
  it("includes agent subprocesses Electron never reports", () => {
    const merged = mergeProcesses(METRICS, TREE);

    const agent = merged.find((proc) => proc.pid === 502);
    expect(agent).toMatchObject({
      origin: "descendant",
      label: "node cli.js --task 42",
      rssBytes: 2_000_000_000,
    });
  });

  it("prefers RSS from the process tree over Electron's working set", () => {
    const browser = mergeProcesses(METRICS, TREE).find(
      (proc) => proc.pid === 500,
    );

    expect(browser).toMatchObject({
      origin: "electron",
      electronType: "Browser",
      rssBytes: 350_000_000,
      ppid: 1,
    });
  });

  it("falls back to Electron metrics when the tree is unavailable", () => {
    const merged = mergeProcesses(METRICS, null);

    expect(merged.map((proc) => proc.pid)).toEqual([501, 500]);
    // workingSetSize is in kilobytes.
    expect(merged[0].rssBytes).toBe(400_000 * 1024);
  });

  it("sorts by resident memory, largest first", () => {
    expect(mergeProcesses(METRICS, TREE).map((proc) => proc.pid)).toEqual([
      502, 501, 500,
    ]);
  });

  it("counts each pid once when both sources see it", () => {
    expect(mergeProcesses(METRICS, TREE)).toHaveLength(3);
  });
});
