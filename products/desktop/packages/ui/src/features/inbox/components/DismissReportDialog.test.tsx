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
  it("keeps dismiss nomenclature while explaining temporary behavior", async () => {
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
      screen.getByText('Dismiss report "Checkout errors"?'),
    ).toBeInTheDocument();
    expect(screen.getByText(/dismisses the report for everyone/)).toBeTruthy();

    await user.click(screen.getByRole("radio", { name: "Already fixed" }));

    expect(
      screen.getByText('Dismiss report "Checkout errors"?'),
    ).toBeInTheDocument();
    expect(screen.getByText(/dismisses the report until/)).toBeTruthy();
    expect(
      screen.getByRole("button", { name: "Dismiss report" }),
    ).toBeInTheDocument();
  });

  it("preselects a context-menu reason and focuses the note", () => {
    render(
      <DismissReportDialog
        open
        onOpenChange={vi.fn()}
        report={report}
        isSubmitting={false}
        snoozeDisabledReason={null}
        initialReason="other"
        onConfirm={vi.fn()}
      />,
    );

    expect(
      screen.getByRole("radio", { name: "Something else…" }),
    ).toBeChecked();
    expect(screen.getByPlaceholderText("Optional: add detail")).toHaveFocus();
  });
});
