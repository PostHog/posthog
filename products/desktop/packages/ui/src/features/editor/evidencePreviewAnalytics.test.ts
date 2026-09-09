import type { PostHogAPIClient } from "@posthog/api-client/posthog-client";
import { setRootContainer } from "@posthog/di/container";
import { ANALYTICS_EVENTS } from "@posthog/shared/analytics-events";
import { Container } from "inversify";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { ANALYTICS_TRACKER } from "../../shell/analytics";
import type { EvidenceLinkTarget } from "../../utils/evidenceLinks";
import { fetchEvidencePreview } from "./evidencePreview";
import {
  fetchEvidencePreviewTimed,
  trackEvidencePreviewShown,
} from "./evidencePreviewAnalytics";

vi.mock("./evidencePreview", () => ({
  fetchEvidencePreview: vi.fn(),
}));

function bindTracker() {
  const track = vi.fn();
  const container = new Container();
  container.bind(ANALYTICS_TRACKER).toConstantValue({ track });
  setRootContainer(container);
  return track;
}

const client = {} as PostHogAPIClient;

describe("evidence preview analytics", () => {
  beforeEach(() => {
    vi.mocked(fetchEvidencePreview).mockReset();
  });

  it("no-ops the tracking when no analytics service is bound", async () => {
    // Order-dependent: setRootContainer has no reset, so this must run
    // before any bindTracker call or it silently tests nothing.
    vi.mocked(fetchEvidencePreview).mockResolvedValue({ title: "Anything" });
    await expect(
      fetchEvidencePreviewTimed(client, { kind: "flag", id: "42" }, "hover"),
    ).resolves.toEqual({ title: "Anything" });
    expect(() => trackEvidencePreviewShown("flag", false)).not.toThrow();
  });

  it("reports ready with kind, source and load latency — and no reference contents", async () => {
    const target: EvidenceLinkTarget = { kind: "insight", id: "9pQx3" };
    vi.mocked(fetchEvidencePreview).mockResolvedValue({
      title: "Acme Corp checkout funnel",
    });
    const track = bindTracker();

    const preview = await fetchEvidencePreviewTimed(client, target, "hover");

    expect(preview?.title).toBe("Acme Corp checkout funnel");
    expect(track).toHaveBeenCalledTimes(1);
    const [event, properties] = track.mock.calls[0];
    expect(event).toBe(ANALYTICS_EVENTS.EVIDENCE_PREVIEW_READY);
    expect(properties).toMatchObject({
      kind: "insight",
      source: "hover",
      has_preview: true,
    });
    expect(properties.latency_ms).toBeGreaterThanOrEqual(0);
    expect(JSON.stringify(properties)).not.toContain("9pQx3");
    expect(JSON.stringify(properties)).not.toContain("Acme");
  });

  it("reports failed with latency when the lookup throws, and rethrows", async () => {
    const target: EvidenceLinkTarget = {
      kind: "hogql",
      id: "SELECT secret_column FROM secret_table",
    };
    vi.mocked(fetchEvidencePreview).mockRejectedValue(
      new Error("Query failed: SELECT secret_column FROM secret_table"),
    );
    const track = bindTracker();

    await expect(
      fetchEvidencePreviewTimed(client, target, "prefetch"),
    ).rejects.toThrow("Query failed");

    expect(track).toHaveBeenCalledTimes(1);
    const [event, properties] = track.mock.calls[0];
    expect(event).toBe(ANALYTICS_EVENTS.EVIDENCE_PREVIEW_FAILED);
    expect(properties).toMatchObject({ kind: "hogql", source: "prefetch" });
    expect(properties.latency_ms).toBeGreaterThanOrEqual(0);
    expect(JSON.stringify(properties)).not.toContain("secret_column");
    expect(JSON.stringify(properties)).not.toContain(target.id);
  });

  it("reports shown with the cache state and no reference id", () => {
    const track = bindTracker();

    trackEvidencePreviewShown("insight", false);

    expect(track).toHaveBeenCalledWith(
      ANALYTICS_EVENTS.EVIDENCE_PREVIEW_SHOWN,
      {
        kind: "insight",
        cache: "miss",
      },
    );
  });
});
