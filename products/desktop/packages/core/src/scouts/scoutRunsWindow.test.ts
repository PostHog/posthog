import type { ScoutRun } from "@posthog/api-client/posthog-client";
import { describe, expect, it } from "vitest";
import {
  fetchScoutRunsWindow,
  SCOUT_RUNS_WINDOW_HOURS,
  type ScoutRunsClient,
  type ScoutRunsWindow,
  scoutRunsWindowLabel,
} from "./scoutRunsWindow";

const NOW = new Date("2026-06-10T12:00:00.000Z");

function makeRun(id: string, startedAt: string | null): ScoutRun {
  return {
    run_id: id,
    skill_name: "signals-scout-general",
    skill_version: 1,
    status: "completed",
    started_at: startedAt,
    completed_at: startedAt,
    task_id: null,
    task_run_id: null,
    task_url: null,
    summary: "",
    emitted_count: 0,
    emitted_finding_ids: [],
  };
}

function clientFromPages(pages: ScoutRun[][]): {
  client: ScoutRunsClient;
  calls: Array<{ date_from?: string; date_to?: string; limit?: number }>;
} {
  const calls: Array<{ date_from?: string; date_to?: string; limit?: number }> =
    [];
  let index = 0;
  return {
    calls,
    client: {
      listScoutRuns: (_projectId, params) => {
        calls.push({ ...params });
        const page = pages[index] ?? [];
        index++;
        return Promise.resolve(page);
      },
    },
  };
}

function fullPage(prefix: string, hourOffset: number): ScoutRun[] {
  return Array.from({ length: 100 }, (_, i) =>
    makeRun(
      `${prefix}-${i}`,
      new Date(
        NOW.getTime() - hourOffset * 3_600_000 - i * 60_000,
      ).toISOString(),
    ),
  );
}

describe("fetchScoutRunsWindow", () => {
  it("returns a complete window from a single short page", async () => {
    const runs = [makeRun("a", "2026-06-10T11:00:00.000Z")];
    const { client, calls } = clientFromPages([runs]);

    const window = await fetchScoutRunsWindow(client, 1, NOW);

    expect(window.complete).toBe(true);
    expect(window.runs).toHaveLength(1);
    expect(calls).toHaveLength(1);
    expect(calls[0]?.date_from).toBe(
      new Date(
        NOW.getTime() - SCOUT_RUNS_WINDOW_HOURS * 3_600_000,
      ).toISOString(),
    );
    expect(calls[0]?.date_to).toBeUndefined();
    expect(calls[0]?.limit).toBe(100);
  });

  it("walks date_to past full pages and dedupes boundary repeats", async () => {
    const first = fullPage("p1", 0);
    const boundary = first[99];
    if (!boundary) throw new Error("expected boundary run");
    // Second page re-includes the boundary run (timestamp drift), then ends short.
    const second = [boundary, makeRun("p2-0", "2026-06-10T01:00:00.000Z")];
    const { client, calls } = clientFromPages([first, second]);

    const window = await fetchScoutRunsWindow(client, 1, NOW);

    expect(window.complete).toBe(true);
    expect(window.runs).toHaveLength(101);
    expect(calls).toHaveLength(2);
    expect(calls[1]?.date_to).toBe(boundary.started_at);
  });

  it("reports an incomplete window when the cursor cannot advance", async () => {
    const page = fullPage("p1", 0);
    const { client } = clientFromPages([page, page]);

    const window = await fetchScoutRunsWindow(client, 1, NOW);

    expect(window.complete).toBe(false);
    expect(window.runs).toHaveLength(100);
  });

  it("stops at the page cap and reports incomplete", async () => {
    const pages = Array.from({ length: 12 }, (_, i) => fullPage(`p${i}`, i));
    const { client, calls } = clientFromPages(pages);

    const window = await fetchScoutRunsWindow(client, 1, NOW);

    expect(window.complete).toBe(false);
    expect(window.runs).toHaveLength(1000);
    expect(calls).toHaveLength(10);
  });
});

describe("scoutRunsWindowLabel", () => {
  it.each([
    {
      name: "complete window",
      window: { runs: [], complete: true } as ScoutRunsWindow,
      expected: "last 3 days",
    },
    {
      name: "truncated window",
      window: { runs: [], complete: false } as ScoutRunsWindow,
      expected: "last 3 days · truncated",
    },
    {
      name: "undefined window",
      window: undefined,
      expected: "last 3 days",
    },
  ])("names the $name", ({ window, expected }) => {
    expect(scoutRunsWindowLabel(window)).toBe(expected);
  });
});
