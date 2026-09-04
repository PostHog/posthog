import type { SignalReport } from "@posthog/shared/types";
import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

const { useReportClaim } = vi.hoisted(() => ({
  useReportClaim: vi.fn(),
}));

vi.mock("@posthog/ui/features/inbox/hooks/useReportClaim", () => ({
  useReportClaim,
}));

import { ReportOwnerSection } from "@posthog/ui/features/inbox/components/ReportOwnerSection";

function fakeReport(overrides: Partial<SignalReport> = {}): SignalReport {
  return {
    id: "r1",
    title: "Test report",
    summary: "Summary",
    status: "ready",
    total_weight: 1,
    signal_count: 1,
    created_at: "2026-06-05T00:00:00Z",
    updated_at: "2026-06-05T00:00:00Z",
    artefact_count: 0,
    ...overrides,
  };
}

describe("ReportOwnerSection", () => {
  afterEach(cleanup);

  it.each([
    {
      name: "an agent claim, which can be taken over or released",
      report: fakeReport({
        assignee: { kind: "agent", agent: "scout-runner" },
        work_state: "working",
      }),
      canRelease: true,
      expectedText: "scout-runner",
      expectedAction: "Take over",
      expectRelease: true,
    },
    {
      name: "an unclaimed report, which can only be claimed",
      report: fakeReport(),
      canRelease: false,
      expectedText: "Nobody has claimed this report yet.",
      expectedAction: "Claim",
      expectRelease: false,
    },
  ])(
    "shows $name",
    ({ report, canRelease, expectedText, expectedAction, expectRelease }) => {
      useReportClaim.mockReturnValue({
        canRelease,
        mutation: { isPending: false, mutate: vi.fn() },
      });

      render(<ReportOwnerSection report={report} />);

      expect(
        screen.getAllByText(expectedText, { exact: false }).length,
      ).toBeGreaterThan(0);
      expect(screen.getByText(expectedAction)).toBeTruthy();
      expect(Boolean(screen.queryByText("Release"))).toBe(expectRelease);
    },
  );
});
