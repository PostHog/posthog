import type {
  SignalReport,
  SignalReportStatus,
} from "@posthog/shared/domain-types";
import { describe, expect, it } from "vitest";
import { reportAutoCloseTransition } from "./reportAutoClose";

function report(overrides: Partial<SignalReport>): SignalReport {
  return {
    id: "r1",
    title: "A report",
    summary: "",
    status: "ready",
    total_weight: 1,
    signal_count: 1,
    created_at: "2024-01-01T00:00:00Z",
    updated_at: "2024-01-01T00:00:00Z",
    artefact_count: 0,
    ...overrides,
  };
}

describe("reportAutoCloseTransition", () => {
  it("tracks the id on first non-terminal render", () => {
    expect(reportAutoCloseTransition(null, report({ id: "r1" }))).toEqual({
      nextActiveReportId: "r1",
      closed: false,
    });
  });

  it("keeps tracking on further non-terminal updates for the same report", () => {
    expect(
      reportAutoCloseTransition("r1", report({ id: "r1", status: "ready" })),
    ).toEqual({ nextActiveReportId: "r1", closed: false });
  });

  it("switches the tracked id when a different non-terminal report opens", () => {
    expect(reportAutoCloseTransition("r1", report({ id: "r2" }))).toEqual({
      nextActiveReportId: "r2",
      closed: false,
    });
  });

  it.each<SignalReportStatus>(["resolved", "suppressed"])(
    "does not close a report that mounts already %s (Archive case)",
    (status) => {
      expect(
        reportAutoCloseTransition(null, report({ id: "r1", status })),
      ).toEqual({ nextActiveReportId: null, closed: false });
    },
  );

  it.each<SignalReportStatus>(["resolved", "suppressed"])(
    "closes and clears the tracked id when the open report transitions to %s",
    (status) => {
      expect(
        reportAutoCloseTransition("r1", report({ id: "r1", status })),
      ).toEqual({ nextActiveReportId: null, closed: true });
    },
  );

  it("does not close when a terminal update arrives for a different id than the tracked one", () => {
    expect(
      reportAutoCloseTransition("r1", report({ id: "r2", status: "resolved" })),
    ).toEqual({ nextActiveReportId: "r1", closed: false });
  });
});
