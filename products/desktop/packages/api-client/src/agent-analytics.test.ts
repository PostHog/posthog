import { describe, expect, it } from "vitest";
import {
  type AgentAnalyticsRaw,
  buildAgentAnalyticsQueries,
  EMPTY_AGENT_ANALYTICS,
  type HogQLGrid,
  shapeAgentAnalytics,
} from "./agent-analytics";

const grid = (results: unknown[][]): HogQLGrid => ({ results, columns: [] });

// A 14-day daily series where every day is identical, so prior(7) === recent(7)
// → zero deltas. Columns: [day, cost, sessions, errors, generations].
function flatDaily(): unknown[][] {
  return Array.from({ length: 14 }, (_, i) => [
    `2026-06-${String(i + 1).padStart(2, "0")}T00:00:00`,
    2, // cost
    5, // sessions
    1, // errors
    10, // generations
  ]);
}

describe("buildAgentAnalyticsQueries", () => {
  it("scopes to any agent-platform traffic when no application id", () => {
    const q = buildAgentAnalyticsQueries();
    // Attribution key, not $ai_origin — the gateway's cost event lacks origin.
    expect(q.kpi).toContain("notEmpty(properties.$agent_application_id)");
    expect(q.kpi).not.toContain("$ai_origin");
    expect(q.kpi).not.toContain("$agent_application_id =");
    expect(q.kpi).toContain("event = '$ai_generation'");
    expect(q.toolErrors).toContain("event = '$ai_span'");
  });

  it("narrows to a single application id when given", () => {
    const id = "11111111-2222-3333-4444-555566667777";
    const q = buildAgentAnalyticsQueries(id);
    expect(q.kpi).toContain(`properties.$agent_application_id = '${id}'`);
    expect(q.byModel).toContain(`properties.$agent_application_id = '${id}'`);
  });

  it("rejects a non-uuid application id", () => {
    expect(() => buildAgentAnalyticsQueries("app-uuid-123")).toThrow(
      /must be a UUID/,
    );
  });
});

describe("shapeAgentAnalytics", () => {
  it("returns an empty board for empty grids", () => {
    const out = shapeAgentAnalytics({});
    expect(out.empty).toBe(true);
    expect(out.kpis).toEqual(EMPTY_AGENT_ANALYTICS.kpis);
    expect(out.byAgent).toEqual([]);
    expect(out.deltas).toEqual({
      spend: null,
      sessions: null,
      failureRatePoints: null,
    });
  });

  it("derives KPIs incl. failure rate from generations", () => {
    const raw: Partial<AgentAnalyticsRaw> = {
      // cost, sessions, errors, generations, p95
      kpi: grid([[12.5, 8, 3, 12, 4.2]]),
    };
    const out = shapeAgentAnalytics(raw);
    expect(out.kpis.spendUsd).toBe(12.5);
    expect(out.kpis.sessions).toBe(8);
    expect(out.kpis.failureRate).toBeCloseTo(3 / 12);
    expect(out.kpis.p95LatencyS).toBe(4.2);
    expect(out.empty).toBe(false);
  });

  it("coerces numeric strings (HogQL returns decimals as strings)", () => {
    const out = shapeAgentAnalytics({
      kpi: grid([["1.50", "4", "0", "4", "2"]]),
    });
    expect(out.kpis.spendUsd).toBe(1.5);
    expect(out.kpis.sessions).toBe(4);
    expect(out.kpis.failureRate).toBe(0);
  });

  it("builds a 14-day daily series with zero deltas for a flat trend", () => {
    const out = shapeAgentAnalytics({ daily: grid(flatDaily()) });
    expect(out.daily.labels).toHaveLength(14);
    expect(out.daily.spend).toHaveLength(14);
    expect(out.daily.failureRate.every((r) => r === 0.1)).toBe(true);
    // prior 7 === recent 7 → 0% change, and failure-rate delta is 0pp.
    expect(out.deltas.spend).toBe(0);
    expect(out.deltas.sessions).toBe(0);
    expect(out.deltas.failureRatePoints).toBe(0);
  });

  it("computes a positive spend delta when recent exceeds prior", () => {
    // 7 days at cost 1, then 7 days at cost 3 → +200%.
    const days = Array.from({ length: 14 }, (_, i) => [
      `2026-06-${String(i + 1).padStart(2, "0")}T00:00:00`,
      i < 7 ? 1 : 3,
      1,
      0,
      1,
    ]);
    const out = shapeAgentAnalytics({ daily: grid(days) });
    expect(out.deltas.spend).toBeCloseTo(200);
  });

  it("maps per-agent rows and resolves names via the id→name map", () => {
    const raw: Partial<AgentAnalyticsRaw> = {
      // agent_id, sessions, generations, cost, tokens, errors, p95
      perAgent: grid([
        ["11111111-2222-3333-4444-555566667777", 5, 10, 4, 2000, 2, 1.5],
        ["aaaa", 1, 4, 0.5, 100, 0, 0.2],
      ]),
    };
    const names = new Map([
      ["11111111-2222-3333-4444-555566667777", "Support Bot"],
    ]);
    const out = shapeAgentAnalytics(raw, names);
    expect(out.byAgent[0]).toMatchObject({
      name: "Support Bot",
      sessions: 5,
      spendUsd: 4,
      tokens: 2000,
      p95LatencyS: 1.5,
    });
    expect(out.byAgent[0].failureRate).toBeCloseTo(2 / 10);
    // Unknown id falls back to a short id.
    expect(out.byAgent[1].name).toBe("aaaa");
  });

  it("maps model spend and tool error rates", () => {
    const out = shapeAgentAnalytics({
      byModel: grid([["claude-opus-4-8", 9.99, 42]]),
      toolErrors: grid([
        ["search", 20, 4],
        ["fetch", 5, 0],
      ]),
    });
    expect(out.byModel[0]).toEqual({
      model: "claude-opus-4-8",
      spendUsd: 9.99,
      calls: 42,
    });
    expect(out.toolErrors[0].errorRate).toBeCloseTo(4 / 20);
    expect(out.toolErrors[1].errorRate).toBe(0);
  });

  it("ignores non-array rows defensively", () => {
    const out = shapeAgentAnalytics({
      kpi: grid([[1, 1, 0, 1, 1]]),
      perAgent: {
        results: [null, "oops"] as unknown as unknown[][],
        columns: [],
      },
    });
    expect(out.byAgent).toEqual([]);
    expect(out.empty).toBe(false);
  });
});
