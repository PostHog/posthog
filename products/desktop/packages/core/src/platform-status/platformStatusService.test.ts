import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { PlatformStatusClient } from "./identifiers";
import { PlatformStatusService } from "./platformStatusService";
import {
  platformStatusStore,
  UNKNOWN_PLATFORM_STATUS,
} from "./platformStatusStore";

const statusPageUrl = "https://www.posthogstatus.com/eu";

describe("PlatformStatusService", () => {
  beforeEach(() => {
    vi.useFakeTimers();
    platformStatusStore.getState().setStatus(UNKNOWN_PLATFORM_STATUS);
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it("checks the selected sign-in region before authentication completes", async () => {
    const client: PlatformStatusClient = {
      getStatus: vi.fn().mockResolvedValue({
        status: "partial_outage",
        statusPageUrl,
      }),
    };
    const service = new PlatformStatusService(client);

    service.setRegion("eu");
    await vi.runAllTicks();

    expect(client.getStatus).toHaveBeenCalledWith("eu");
    expect(platformStatusStore.getState().status).toEqual({
      status: "partial_outage",
      statusPageUrl,
    });
  });

  it("clears the status when the status request fails", async () => {
    const client: PlatformStatusClient = {
      getStatus: vi.fn().mockRejectedValue(new Error("unavailable")),
    };
    const service = new PlatformStatusService(client);

    service.setRegion("us");
    await vi.runAllTicks();

    expect(platformStatusStore.getState().status).toEqual(
      UNKNOWN_PLATFORM_STATUS,
    );
  });
});
