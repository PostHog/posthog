import type { SignalReport } from "@posthog/shared/types";
import { renderHook } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const mockTrack = vi.hoisted(() => vi.fn());

vi.mock("@posthog/ui/shell/analytics", () => ({ track: mockTrack }));

vi.mock("@posthog/ui/features/inbox/hooks/useInboxAllReports", () => ({
  useInboxAllReports: () => ({ scopedReports: [] }),
}));

import { useReportOpenTracker } from "./useReportOpenTracker";

function report(id: string): SignalReport {
  return {
    id,
    title: `Report ${id}`,
    summary: null,
    status: "ready",
    total_weight: 1,
    signal_count: 1,
    created_at: "2024-01-01T00:00:00Z",
    updated_at: "2024-01-01T00:00:00Z",
    artefact_count: 0,
    implementation_pr_url: null,
  } as SignalReport;
}

function closeCalls(): Array<[string, Record<string, unknown>, unknown]> {
  return mockTrack.mock.calls.filter(
    (call) => call[0] === "Inbox report closed",
  ) as Array<[string, Record<string, unknown>, unknown]>;
}

describe("useReportOpenTracker", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("flushes the close on pagehide and does not fire it again on unmount", () => {
    const { unmount } = renderHook(() =>
      useReportOpenTracker(report("r1"), "reports"),
    );

    window.dispatchEvent(new Event("pagehide"));
    unmount();

    expect(closeCalls()).toHaveLength(1);
    const [, properties, options] = closeCalls()[0];
    expect(properties).toMatchObject({
      report_id: "r1",
      close_method: "page_unload",
    });
    // The unload flush must leave before the page goes.
    expect(options).toEqual({ send_instantly: true });
  });

  it("labels an in-app unmount close `unmount`", () => {
    const { unmount } = renderHook(() =>
      useReportOpenTracker(report("r1"), "reports"),
    );

    unmount();

    expect(closeCalls()).toHaveLength(1);
    expect(closeCalls()[0][1]).toMatchObject({
      report_id: "r1",
      close_method: "unmount",
    });
  });

  it("labels a report→report switch close `next_report`", () => {
    const { rerender, unmount } = renderHook(
      ({ id }: { id: string }) => useReportOpenTracker(report(id), "reports"),
      { initialProps: { id: "r1" } },
    );

    rerender({ id: "r2" });

    expect(closeCalls()).toHaveLength(1);
    expect(closeCalls()[0][1]).toMatchObject({
      report_id: "r1",
      close_method: "next_report",
    });

    // The switch resets the default, so the next teardown is a plain unmount.
    unmount();
    expect(closeCalls()[1][1]).toMatchObject({
      report_id: "r2",
      close_method: "unmount",
    });
  });
});
