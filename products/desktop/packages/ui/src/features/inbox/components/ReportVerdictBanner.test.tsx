import type { SignalReport, Task } from "@posthog/shared/types";
import { useReportChatPanelStore } from "@posthog/ui/features/inbox/stores/reportChatPanelStore";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

const { useReportTasks } = vi.hoisted(() => ({ useReportTasks: vi.fn() }));

vi.mock(
  "@posthog/ui/features/inbox/hooks/useReportTasks",
  async (importOriginal) => {
    const actual =
      await importOriginal<
        typeof import("@posthog/ui/features/inbox/hooks/useReportTasks")
      >();
    return { ...actual, useReportTasks };
  },
);

vi.mock("@posthog/ui/features/inbox/hooks/useCreatePrReport", () => ({
  useCreatePrReport: () => ({ createPrReport: vi.fn(), isCreatingPr: false }),
}));

vi.mock("@posthog/ui/features/inbox/hooks/useInboxBulkActions", () => ({
  useInboxBulkActions: () => ({
    isSnoozing: false,
    snoozeDisabledReason: null,
    snoozeSelected: vi.fn(),
  }),
}));

vi.mock("@posthog/ui/features/inbox/hooks/useInboxReportDismissAction", () => ({
  useInboxReportDismissAction: () => ({
    dialog: null,
    openDialog: vi.fn(),
  }),
}));

vi.mock("@posthog/ui/features/inbox/hooks/useInboxReports", () => ({
  useInboxReportArtefacts: () => ({ data: { results: [] } }),
}));

vi.mock("@posthog/ui/features/inbox/hooks/useReportActionTracker", () => ({
  useReportActionTracker: () => vi.fn(),
}));

import { ReportVerdictBanner } from "./ReportVerdictBanner";

const report = {
  id: "report-1",
  status: "ready",
  actionability: "not_actionable",
  implementation_pr_url: null,
  implementation_pr_merged: false,
} as SignalReport;

const discussionTask = {
  task: { id: "task-1" } as Task,
  purpose: "discussion",
  purposeLabel: "Discussion",
  startedAt: "2026-08-26T00:00:00.000Z",
};

describe("ReportVerdictBanner", () => {
  beforeEach(() => {
    useReportChatPanelStore.setState({
      open: false,
      startedTaskIdByReport: {},
    });
    useReportTasks.mockReturnValue({ data: [], isLoading: false });
  });

  it("hides the non-selectable detail actions after engagement", async () => {
    const user = userEvent.setup();
    render(<ReportVerdictBanner report={report} initialEngagementOnly />);

    const askButton = screen.getByText("Ask about it");
    expect(askButton.closest(".select-none")).not.toBeNull();

    await user.click(askButton);

    expect(screen.queryByText("Ask about it")).not.toBeInTheDocument();
  });

  it("stays hidden when the report already has a discussion", () => {
    useReportTasks.mockReturnValue({
      data: [discussionTask],
      isLoading: false,
    });

    render(<ReportVerdictBanner report={report} initialEngagementOnly />);

    expect(screen.queryByText("Ask about it")).not.toBeInTheDocument();
  });
});
