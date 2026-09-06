import { describe, expect, it, vi } from "vitest";
import { getPlatformStatus } from "./getPlatformStatus";

const statusResponse = {
  component_groups: [
    {
      name: "US Cloud 🇺🇸",
      components: [
        { name: "App", status: "degraded_performance" },
        { name: "PostHog Desktop", status: "partial_outage" },
      ],
    },
    {
      name: "EU Cloud 🇪🇺",
      components: [
        { name: "App", status: "operational" },
        { name: "PostHog Desktop", status: "operational" },
      ],
    },
  ],
};

describe("getPlatformStatus", () => {
  it.each([
    ["us", "partial_outage", "https://www.posthogstatus.com/us"],
    ["eu", "operational", "https://www.posthogstatus.com/eu"],
  ] as const)(
    "returns the status for the selected %s region",
    async (region, status, statusPageUrl) => {
      const fetcher = vi.fn().mockResolvedValue({
        ok: true,
        json: () => Promise.resolve(statusResponse),
      });
      await expect(getPlatformStatus(region, fetcher)).resolves.toEqual({
        status,
        statusPageUrl,
      });
    },
  );

  it("returns unknown when the status page cannot answer", async () => {
    const fetcher = vi.fn().mockResolvedValue({ ok: false });
    await expect(getPlatformStatus("us", fetcher)).resolves.toEqual({
      status: "unknown",
      statusPageUrl: "https://www.posthogstatus.com/us",
    });
  });
});
