import { describe, expect, it } from "vitest";
import {
  collectMemorySnapshot,
  flattenMemorySnapshot,
} from "./crash-diagnostics";

function metric(
  type: string,
  workingSetSize: number,
  peakWorkingSetSize: number,
): Electron.ProcessMetric {
  return {
    type,
    memory: { workingSetSize, peakWorkingSetSize, privateBytes: 0 },
  } as unknown as Electron.ProcessMetric;
}

describe("collectMemorySnapshot", () => {
  it("sums working set, tracks peak, and groups by process type", () => {
    const snapshot = collectMemorySnapshot(() => [
      metric("Browser", 100, 150),
      metric("Tab", 200, 500),
      metric("Tab", 50, 60),
      metric("GPU", 80, 90),
    ]);

    expect(snapshot).toEqual({
      totalWorkingSetKb: 430,
      peakWorkingSetKb: 500,
      processCount: 4,
      byType: { Browser: 100, Tab: 250, GPU: 80 },
    });
  });

  it("returns a zeroed snapshot for no processes", () => {
    expect(collectMemorySnapshot(() => [])).toEqual({
      totalWorkingSetKb: 0,
      peakWorkingSetKb: 0,
      processCount: 0,
      byType: {},
    });
  });

  it("returns undefined instead of throwing (crash handler must not fail)", () => {
    expect(
      collectMemorySnapshot(() => {
        throw new Error("getAppMetrics unavailable");
      }),
    ).toBeUndefined();
  });
});

describe("flattenMemorySnapshot", () => {
  it("flattens scalars and serializes byType for PostHog", () => {
    expect(
      flattenMemorySnapshot({
        totalWorkingSetKb: 430,
        peakWorkingSetKb: 500,
        processCount: 4,
        byType: { Browser: 100, Tab: 250, GPU: 80 },
      }),
    ).toEqual({
      memoryTotalWorkingSetKb: 430,
      memoryPeakWorkingSetKb: 500,
      memoryProcessCount: 4,
      memoryByType: '{"Browser":100,"Tab":250,"GPU":80}',
    });
  });

  it("returns an empty object when no snapshot was collected", () => {
    expect(flattenMemorySnapshot(undefined)).toEqual({});
  });
});
