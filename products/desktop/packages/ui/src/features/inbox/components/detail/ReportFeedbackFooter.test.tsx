import { ANALYTICS_EVENTS } from "@posthog/shared";
import type { SignalReport } from "@posthog/shared/types";
import { Theme } from "@radix-ui/themes";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

const { track } = vi.hoisted(() => ({ track: vi.fn() }));

vi.mock("@posthog/ui/shell/analytics", () => ({ track }));

import { ReportFeedbackFooter } from "./ReportFeedbackFooter";

const report = {
  id: "report-1",
  title: "Some report",
  status: "ready",
  created_at: "2026-07-29T00:00:00.000Z",
  priority: "P1",
  actionability: "immediately_actionable",
  implementation_pr_url: null,
} as unknown as SignalReport;

function renderFooter() {
  render(
    <Theme>
      <ReportFeedbackFooter report={report} />
    </Theme>,
  );
}

describe("ReportFeedbackFooter", () => {
  beforeEach(() => {
    track.mockReset();
  });

  it("asks for a rating before one is given and hides the note field", () => {
    renderFooter();
    expect(screen.getByText("Was this report useful?")).toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: "Add a note" }),
    ).not.toBeInTheDocument();
    expect(track).not.toHaveBeenCalled();
  });

  it("emits exactly one feedback event per thumb and treats a re-click as a no-op", async () => {
    const user = userEvent.setup();
    renderFooter();

    await user.click(
      screen.getByRole("button", { name: "This report was useful" }),
    );

    expect(track).toHaveBeenCalledTimes(1);
    expect(track).toHaveBeenCalledWith(ANALYTICS_EVENTS.INBOX_REPORT_FEEDBACK, {
      report_id: "report-1",
      report_age_hours: expect.any(Number),
      priority: "P1",
      actionability: "immediately_actionable",
      sentiment: "positive",
      has_pr: false,
      surface: "detail_footer",
    });

    // Re-clicking the already-selected thumb must not fire a second event.
    await user.click(
      screen.getByRole("button", { name: "This report was useful" }),
    );
    expect(track).toHaveBeenCalledTimes(1);
  });

  it("sends an optional note as a separate event only after a rating", async () => {
    const user = userEvent.setup();
    renderFooter();

    await user.click(
      screen.getByRole("button", { name: "This report was not useful" }),
    );
    expect(track).toHaveBeenCalledTimes(1);

    await user.click(screen.getByRole("button", { name: "Add a note" }));
    await user.type(
      screen.getByRole("textbox", { name: "Add a note about this report" }),
      "some detail",
    );
    await user.click(screen.getByRole("button", { name: "Send" }));

    expect(track).toHaveBeenCalledTimes(2);
    expect(track).toHaveBeenLastCalledWith(
      ANALYTICS_EVENTS.INBOX_REPORT_FEEDBACK_NOTE,
      {
        report_id: "report-1",
        report_age_hours: expect.any(Number),
        priority: "P1",
        actionability: "immediately_actionable",
        sentiment: "negative",
        has_pr: false,
        surface: "detail_footer",
        note: "some detail",
      },
    );
    expect(screen.getByText("Note added")).toBeInTheDocument();
  });
});
