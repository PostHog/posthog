import type { PostHogAPIClient } from "@posthog/api-client/posthog-client";
import { describe, expect, it, vi } from "vitest";
import { InboxBulkActionService } from "./bulkActionService";

function fakeClient(overrides: Partial<PostHogAPIClient> = {}) {
  return {
    updateSignalReportState: vi.fn().mockResolvedValue({}),
    deleteSignalReport: vi.fn().mockResolvedValue({}),
    reingestSignalReport: vi.fn().mockResolvedValue({}),
    ...overrides,
  } as unknown as PostHogAPIClient;
}

describe("InboxBulkActionService", () => {
  it("suppresses every selected report and tallies success", async () => {
    const client = fakeClient();
    const service = new InboxBulkActionService();
    const result = await service.suppressReports(client, ["a", "b", "c"]);
    expect(client.updateSignalReportState).toHaveBeenCalledTimes(3);
    expect(result).toEqual({ successCount: 3, failureCount: 0 });
  });

  it("forwards the dismissal reason when suppressing", async () => {
    const client = fakeClient();
    const service = new InboxBulkActionService();
    await service.suppressReports(client, ["a"], {
      reason: "already_fixed",
      note: "n",
    });
    const body = (client.updateSignalReportState as ReturnType<typeof vi.fn>)
      .mock.calls[0][1];
    expect(body.state).toBe("suppressed");
    expect(body.dismissal_reason).toBe("already_fixed");
  });

  it("tallies partial failure across the fan-out", async () => {
    const client = fakeClient({
      deleteSignalReport: vi
        .fn()
        .mockResolvedValueOnce({})
        .mockRejectedValueOnce(new Error("boom"))
        .mockResolvedValueOnce({}),
    });
    const service = new InboxBulkActionService();
    const result = await service.deleteReports(client, ["a", "b", "c"]);
    expect(result).toEqual({ successCount: 2, failureCount: 1 });
  });

  it("snoozes and reingests through the api client", async () => {
    const client = fakeClient();
    const service = new InboxBulkActionService();
    await service.snoozeReports(client, ["a"]);
    await service.reingestReports(client, ["b"]);
    expect(client.updateSignalReportState).toHaveBeenCalledTimes(1);
    expect(client.reingestSignalReport).toHaveBeenCalledWith("b");
  });
});
