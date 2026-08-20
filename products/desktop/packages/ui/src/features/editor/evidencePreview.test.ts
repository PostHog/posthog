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
