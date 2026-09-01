import type { SignalReport } from "@posthog/shared/types";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { DismissReportDialog } from "./DismissReportDialog";

const report = {
  id: "report-1",
  title: "Checkout errors",
  summary: "Errors increased.",
  status: "ready",
  total_weight: 1,
  signal_count: 1,
  created_at: "2026-08-28T00:00:00Z",
  updated_at: "2026-08-28T00:00:00Z",
  artefact_count: 0,
} satisfies SignalReport;

describe("DismissReportDialog", () => {
  it("distinguishes a project-wide archive from a temporary pause", async () => {
    const user = userEvent.setup();
    render(
      <DismissReportDialog
        open
        onOpenChange={vi.fn()}
        report={report}
        isSubmitting={false}
        snoozeDisabledReason={null}
        onConfirm={vi.fn()}
      />,
    );

    expect(
      screen.getByText('Archive report "Checkout errors" for everyone?'),
    ).toBeInTheDocument();
    expect(screen.getByText(/archives the report for everyone/)).toBeTruthy();

    await user.click(screen.getByLabelText("Already fixed"));

    expect(
      screen.getByText('Pause report "Checkout errors"?'),
    ).toBeInTheDocument();
    expect(screen.getByText(/pauses the report for everyone/)).toBeTruthy();
    expect(
      screen.getByRole("button", { name: "Pause for everyone" }),
    ).toBeInTheDocument();
  });
});
