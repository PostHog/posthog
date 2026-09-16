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
  it("groups reasons by outcome and explains the choice above the footer", async () => {
    const user = userEvent.setup();
    render(
      <DismissReportDialog
        open
        onOpenChange={vi.fn()}
        report={{
          ...report,
          implementation_pr_url: "https://example.com/pr/1",
        }}
        isSubmitting={false}
        snoozeDisabledReason={null}
        onConfirm={vi.fn()}
      />,
    );

    const description = screen.getByText(/dismisses the report for everyone/);
    expect(
      screen.getByRole("group", { name: "Pause until a new matching signal" }),
    ).toContainElement(screen.getByRole("radio", { name: "Already fixed" }));
    expect(
      screen.getByRole("group", { name: "Don't surface again" }),
    ).toContainElement(screen.getByRole("radio", { name: "Something else…" }));

    await user.click(screen.getByRole("radio", { name: "Already fixed" }));
    expect(description).toHaveTextContent(/dismisses the report for everyone/);
    expect(
      screen.getByText(
        "The report comes back if another matching signal arrives.",
      ),
    ).toBeVisible();

    await user.click(
      screen.getByRole("radio", { name: "Agent's analysis is wrong" }),
    );
    expect(
      screen.getByText(
        "Matching signals won't surface the report again. The open pull request will be closed.",
      ),
    ).toBeVisible();
  });

  it("selects the other reason when the user enters a note first", async () => {
    const user = userEvent.setup();
    const onConfirm = vi.fn();
    render(
      <DismissReportDialog
        open
        onOpenChange={vi.fn()}
        report={report}
        isSubmitting={false}
        snoozeDisabledReason={null}
        onConfirm={onConfirm}
      />,
    );

    const submitButton = screen.getByRole("button", {
      name: "Dismiss report",
    });
    expect(submitButton).toHaveAttribute("aria-disabled", "true");

    await user.type(
      screen.getByLabelText("Details (optional)"),
      "The report needs more context.",
    );

    expect(
      screen.getByRole("radio", { name: "Something else…" }),
    ).toBeChecked();
    expect(submitButton).toHaveAttribute("aria-disabled", "false");

    await user.click(submitButton);

    expect(onConfirm).toHaveBeenCalledWith({
      reason: "other",
      note: "The report needs more context.",
    });
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
    expect(screen.getByLabelText("Details (optional)")).toHaveFocus();
  });
});
