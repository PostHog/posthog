import { render } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const { inboxReportDetailGate } = vi.hoisted(() => ({
  inboxReportDetailGate: vi.fn(() => null),
}));

vi.mock("@posthog/ui/features/inbox/components/InboxReportDetailGate", () => ({
  InboxReportDetailGate: inboxReportDetailGate,
}));

import { ReportDetail } from "@posthog/ui/features/inbox/components/ReportDetail";

describe("ReportDetail", () => {
  beforeEach(() => inboxReportDetailGate.mockClear());

  it("returns to the reports list by default", () => {
    render(<ReportDetail reportId="report-1" />);

    expect(inboxReportDetailGate).toHaveBeenCalledWith(
      expect.objectContaining({
        backTo: "/inbox/reports",
        backLabel: "Back to reports",
      }),
      undefined,
    );
  });
});
