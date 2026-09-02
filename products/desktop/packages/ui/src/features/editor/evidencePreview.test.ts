import type { PostHogAPIClient } from "@posthog/api-client/posthog-client";
import { describe, expect, it, vi } from "vitest";
import { fetchEvidencePreview } from "./evidencePreview";

function fakeClient(overrides: Record<string, unknown>): PostHogAPIClient {
  return overrides as unknown as PostHogAPIClient;
}

describe("fetchEvidencePreview", () => {
  it("reduces a hogql time series to a headline and sparkline", async () => {
    const client = fakeClient({
      runQuery: vi.fn().mockResolvedValue({
        columns: ["day", "active_users"],
        results: [
          ["2026-08-13", 5096547],
          ["2026-08-14", 1506301],
        ],
      }),
    });
    const preview = await fetchEvidencePreview(client, {
      kind: "hogql",
      id: "SELECT ...",
    });
    expect(preview).toMatchObject({
      title: "active_users",
      headline: { value: "1.5M", delta: { direction: "down" } },
      spark: { points: [5096547, 1506301], render: "line" },
    });
  });

  it("summarizes a hogql table result by counts, never echoing column titles", async () => {
    // Text cells keep the grid unchartable, so it stays a table.
    const client = fakeClient({
      runQuery: vi.fn().mockResolvedValue({
        columns: ["arrayJoin(events.event)", "ifNull(count(), 0)"],
        results: [
          ["$pageview", "5096547 events"],
          ["$autocapture", "1506301 events"],
        ],
      }),
    });
    const preview = await fetchEvidencePreview(client, {
      kind: "hogql",
      id: "SELECT arrayJoin(events.event), ifNull(count(), 0) ...",
    });
    expect(preview).toMatchObject({
      title: "2 rows",
      facts: ["2 columns"],
    });
    expect(preview?.detail).toBeUndefined();
    expect(preview?.facts?.join(" ")).not.toContain("arrayJoin");
    expect(preview?.facts?.join(" ")).not.toContain("ifNull");
  });

  it("keeps raw SQL column titles out of a HogQL-backed insight preview", async () => {
    const client = fakeClient({
      getInsightDefinition: vi.fn().mockResolvedValue({
        name: "Events by name",
        description: null,
        query: {
          kind: "DataVisualizationNode",
          source: { kind: "HogQLQuery", query: "SELECT ..." },
          display: "ActionsTable",
        },
        response: {
          columns: ["arrayJoin(events.event)", "count()"],
          results: [
            ["$pageview", 5096547],
            ["$autocapture", 1506301],
          ],
        },
      }),
      runQuery: vi.fn(),
    });
    const preview = await fetchEvidencePreview(client, {
      kind: "insight",
      id: "tbl42",
    });
    expect(preview).toMatchObject({
      title: "Events by name",
      facts: ["2 columns"],
    });
    expect(preview?.detail).toBeUndefined();
    expect(preview?.facts?.join(" ")).not.toContain("arrayJoin");
    expect(preview?.facts?.join(" ")).not.toContain("count()");
  });

  it("shows a single-cell hogql result as its value", async () => {
    const client = fakeClient({
      runQuery: vi.fn().mockResolvedValue({
        columns: ["count"],
        results: [[68831577]],
      }),
    });
    const preview = await fetchEvidencePreview(client, {
      kind: "hogql",
      id: "SELECT count() FROM events",
    });
    expect(preview).toMatchObject({ title: "68,831,577" });
  });

  it("runs a saved insight's query and keeps the insight's name as the title", async () => {
    const client = fakeClient({
      getInsightDefinition: vi.fn().mockResolvedValue({
        name: "Checkout funnel",
        description: null,
        query: {
          kind: "InsightVizNode",
          source: { kind: "TrendsQuery" },
        },
      }),
      runQuery: vi.fn().mockResolvedValue({
        results: [
          {
            label: "DAU",
            days: ["2026-08-13", "2026-08-14"],
            data: [5096547, 1506301],
          },
        ],
      }),
    });
    const preview = await fetchEvidencePreview(client, {
      kind: "insight",
      id: "9pQx3",
    });
    expect(preview).toMatchObject({
      title: "Checkout funnel",
      spark: { points: [5096547, 1506301] },
    });
  });

  it("uses the saved insight result without running a second query", async () => {
    const runQuery = vi.fn();
    const client = fakeClient({
      getInsightDefinition: vi.fn().mockResolvedValue({
        name: "Unique users per variant",
        description: null,
        query: {
          kind: "InsightVizNode",
          source: {
            kind: "TrendsQuery",
            trendsFilter: { display: "ActionsTable" },
          },
        },
        response: {
          results: [
            {
              label: "$feature_flag_called - true",
              breakdown_value: "true",
              data: [],
              days: [],
              aggregated_value: 2,
            },
            {
              label: "$feature_flag_called - None",
              breakdown_value: null,
              data: [],
              days: [],
              aggregated_value: 4,
            },
          ],
        },
      }),
      runQuery,
    });

    await expect(
      fetchEvidencePreview(client, { kind: "insight", id: "sdyR2Pn8" }),
    ).resolves.toMatchObject({
      title: "Unique users per variant",
    });
    expect(runQuery).not.toHaveBeenCalled();
  });

  it("returns null for an insight id that does not resolve", async () => {
    const client = fakeClient({
      getInsightDefinition: vi.fn().mockResolvedValue(null),
    });
    expect(
      await fetchEvidencePreview(client, { kind: "insight", id: "nope" }),
    ).toBeNull();
  });

  it("delegates object kinds to the client's preview lookup", async () => {
    const getEvidencePreview = vi
      .fn()
      .mockResolvedValue({ title: "new-checkout-flow", detail: "Enabled" });
    const client = fakeClient({ getEvidencePreview });
    const preview = await fetchEvidencePreview(client, {
      kind: "flag",
      id: "42",
    });
    expect(getEvidencePreview).toHaveBeenCalledWith("flag", "42");
    expect(preview).toMatchObject({ title: "new-checkout-flow" });
  });
});
