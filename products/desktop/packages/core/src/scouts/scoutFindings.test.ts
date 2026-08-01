import type {
  ScoutEmission,
  ScoutEmissionReportLink,
  ScoutRun,
} from "@posthog/api-client/posthog-client";
import { describe, expect, it } from "vitest";
import {
  availableScoutsFromRows,
  buildScoutFindingRows,
  filterAndSortScoutFindings,
  MAX_FLEET_EMITTED_RUNS,
  mostRecentEmittedRuns,
  SCOUT_FINDINGS_SCOUT_FILTER_ALL,
  SCOUT_FINDINGS_SEVERITY_FILTER_ALL,
  type ScoutFindingsFilter,
  type ScoutFindingsSortKey,
  summarizeEmittedRuns,
  summarizeScoutFindingRows,
} from "./scoutFindings";

function makeRun(overrides: Partial<ScoutRun> = {}): ScoutRun {
  return {
    run_id: "run-1",
    skill_name: "signals-scout-error-tracking",
    skill_version: 3,
    status: "completed",
    started_at: "2026-06-10T11:00:00Z",
    completed_at: "2026-06-10T11:02:00Z",
    task_id: null,
    task_run_id: null,
    task_url: null,
    summary: "EMITTED a finding.",
    emitted_count: 1,
    emitted_finding_ids: [],
    ...overrides,
  };
}

function makeEmission(overrides: Partial<ScoutEmission> = {}): ScoutEmission {
  return {
    id: "em-1",
    run_id: "run-1",
    finding_id: "finding-1",
    description: "Error rate spiked on checkout",
    weight: 1,
    confidence: 0.8,
    severity: "P1",
    tags: [],
    source_id: "src-1",
    emitted_at: "2026-06-10T11:02:00Z",
    ...overrides,
  };
}

const ALL_FILTER: ScoutFindingsFilter = {
  search: "",
  scout: SCOUT_FINDINGS_SCOUT_FILTER_ALL,
  severity: SCOUT_FINDINGS_SEVERITY_FILTER_ALL,
  sort: "newest",
};

describe("mostRecentEmittedRuns", () => {
  it("drops runs that emitted nothing", () => {
    const runs = [
      makeRun({ run_id: "a", emitted_count: 2 }),
      makeRun({ run_id: "b", emitted_count: 0 }),
      makeRun({ run_id: "c", emitted_count: null }),
    ];
    expect(mostRecentEmittedRuns(runs).map((r) => r.run_id)).toEqual(["a"]);
  });

  it("orders by completion, falling back to start time", () => {
    const runs = [
      makeRun({ run_id: "older", completed_at: "2026-06-10T10:00:00Z" }),
      makeRun({ run_id: "newer", completed_at: "2026-06-10T11:30:00Z" }),
      makeRun({
        run_id: "no-complete",
        completed_at: null,
        started_at: "2026-06-10T12:00:00Z",
      }),
    ];
    expect(mostRecentEmittedRuns(runs).map((r) => r.run_id)).toEqual([
      "no-complete",
      "newer",
      "older",
    ]);
  });

  it("caps the result", () => {
    const runs = Array.from({ length: MAX_FLEET_EMITTED_RUNS + 10 }, (_, i) =>
      makeRun({
        run_id: `run-${i}`,
        completed_at: `2026-06-10T${String(i % 24).padStart(2, "0")}:00:00Z`,
      }),
    );
    expect(mostRecentEmittedRuns(runs)).toHaveLength(MAX_FLEET_EMITTED_RUNS);
  });
});

describe("buildScoutFindingRows", () => {
  it("joins emissions to their run and report by source_id", () => {
    const run = makeRun({ run_id: "run-1" });
    const emission = makeEmission({ run_id: "run-1", source_id: "src-1" });
    const links: ScoutEmissionReportLink[] = [
      {
        finding_id: "finding-1",
        source_id: "src-1",
        report: { id: "rep-1", title: "Checkout errors", status: "potential" },
      },
    ];
    const rows = buildScoutFindingRows([emission], [run], links);
    expect(rows).toHaveLength(1);
    expect(rows[0].run.run_id).toBe("run-1");
    expect(rows[0].linkedReport?.id).toBe("rep-1");
  });

  it("drops emissions whose run is not in the window", () => {
    const rows = buildScoutFindingRows(
      [makeEmission({ run_id: "missing" })],
      [makeRun({ run_id: "run-1" })],
      [],
    );
    expect(rows).toEqual([]);
  });

  it("leaves linkedReport null when there is no matching link or report", () => {
    const rows = buildScoutFindingRows(
      [makeEmission({ run_id: "run-1", source_id: "src-1" })],
      [makeRun({ run_id: "run-1" })],
      [{ finding_id: "finding-1", source_id: "src-1", report: null }],
    );
    expect(rows[0].linkedReport).toBeNull();
  });
});

describe("filterAndSortScoutFindings", () => {
  const run = makeRun({ run_id: "run-1", skill_name: "signals-scout-apm" });
  const other = makeRun({
    run_id: "run-2",
    skill_name: "signals-scout-logs",
  });
  const rows = buildScoutFindingRows(
    [
      makeEmission({
        id: "a",
        run_id: "run-1",
        source_id: "s-a",
        severity: "P0",
        confidence: 0.4,
        description: "latency regression",
        emitted_at: "2026-06-10T09:00:00Z",
      }),
      makeEmission({
        id: "b",
        run_id: "run-2",
        source_id: "s-b",
        severity: "P3",
        confidence: 0.9,
        description: "noisy log volume",
        emitted_at: "2026-06-10T11:00:00Z",
      }),
    ],
    [run, other],
    [],
  );

  it.each<{
    name: string;
    sort: ScoutFindingsSortKey;
    expected: string[];
  }>([
    { name: "newest first (default)", sort: "newest", expected: ["b", "a"] },
    { name: "oldest first", sort: "oldest", expected: ["a", "b"] },
    {
      name: "severity (most severe first)",
      sort: "severity",
      expected: ["a", "b"],
    },
    {
      name: "confidence (highest first)",
      sort: "confidence",
      expected: ["b", "a"],
    },
  ])("sorts by $name", ({ sort, expected }) => {
    expect(
      filterAndSortScoutFindings(rows, { ...ALL_FILTER, sort }).map(
        (r) => r.emission.id,
      ),
    ).toEqual(expected);
  });

  it("filters by scout", () => {
    expect(
      filterAndSortScoutFindings(rows, {
        ...ALL_FILTER,
        scout: "signals-scout-logs",
      }).map((r) => r.emission.id),
    ).toEqual(["b"]);
  });

  it("filters by severity", () => {
    expect(
      filterAndSortScoutFindings(rows, {
        ...ALL_FILTER,
        severity: "P0",
      }).map((r) => r.emission.id),
    ).toEqual(["a"]);
  });

  it("searches finding text and prettified scout name", () => {
    expect(
      filterAndSortScoutFindings(rows, {
        ...ALL_FILTER,
        search: "latency",
      }).map((r) => r.emission.id),
    ).toEqual(["a"]);
    // "Apm" comes from prettifying signals-scout-apm.
    expect(
      filterAndSortScoutFindings(rows, { ...ALL_FILTER, search: "apm" }).map(
        (r) => r.emission.id,
      ),
    ).toEqual(["a"]);
  });
});

describe("summaries", () => {
  it("summarizeEmittedRuns sums emitted counts and distinct scouts", () => {
    const summary = summarizeEmittedRuns([
      makeRun({ run_id: "a", skill_name: "x", emitted_count: 2 }),
      makeRun({ run_id: "b", skill_name: "x", emitted_count: 1 }),
      makeRun({ run_id: "c", skill_name: "y", emitted_count: 3 }),
      makeRun({ run_id: "d", skill_name: "z", emitted_count: 0 }),
    ]);
    expect(summary.totalCount).toBe(6);
    expect(summary.scoutCount).toBe(2);
  });

  it("summarizeScoutFindingRows counts rows, distinct scouts, latest", () => {
    const rows = buildScoutFindingRows(
      [
        makeEmission({
          id: "a",
          run_id: "run-1",
          emitted_at: "2026-06-10T09:00:00Z",
        }),
        makeEmission({
          id: "b",
          run_id: "run-2",
          emitted_at: "2026-06-10T12:00:00Z",
        }),
      ],
      [
        makeRun({ run_id: "run-1", skill_name: "x" }),
        makeRun({ run_id: "run-2", skill_name: "y" }),
      ],
      [],
    );
    const summary = summarizeScoutFindingRows(rows);
    expect(summary.totalCount).toBe(2);
    expect(summary.scoutCount).toBe(2);
    expect(summary.latestEmittedAt).toBe("2026-06-10T12:00:00Z");
  });

  it("availableScoutsFromRows returns per-scout counts sorted by label", () => {
    const rows = buildScoutFindingRows(
      [
        makeEmission({ id: "a", run_id: "run-1" }),
        makeEmission({ id: "b", run_id: "run-1" }),
        makeEmission({ id: "c", run_id: "run-2" }),
      ],
      [
        makeRun({ run_id: "run-1", skill_name: "signals-scout-logs" }),
        makeRun({ run_id: "run-2", skill_name: "signals-scout-apm" }),
      ],
      [],
    );
    const scouts = availableScoutsFromRows(rows);
    // Sorted by prettified label: "Apm" before "Logs".
    expect(scouts.map((s) => s.skillName)).toEqual([
      "signals-scout-apm",
      "signals-scout-logs",
    ]);
    expect(
      scouts.find((s) => s.skillName === "signals-scout-logs")?.count,
    ).toBe(2);
  });
});
