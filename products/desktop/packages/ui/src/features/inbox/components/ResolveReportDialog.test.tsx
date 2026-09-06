import type { SignalReport } from "@posthog/shared/types";
import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { ResolveReportDialog } from "./ResolveReportDialog";

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

describe("ResolveReportDialog", () => {
  it("preselects a context-menu reason and focuses the note", () => {
    render(
      <ResolveReportDialog
        open
        onOpenChange={vi.fn()}
        report={report}
        isSubmitting={false}
        initialReason="other"
        onConfirm={vi.fn()}
      />,
    );

    expect(
      screen.getByRole("radio", { name: "Something else…" }),
    ).toBeChecked();
    expect(
      screen.getByPlaceholderText(
        "Optional: link to the fix or explain what changed",
      ),
    ).toHaveFocus();
  });
});
