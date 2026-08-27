import type { SignalReport, Task } from "@posthog/shared/types";
import type { ReportTaskData } from "@posthog/ui/features/inbox/hooks/useReportTasks";
import { useReportChatPanelStore } from "@posthog/ui/features/inbox/stores/reportChatPanelStore";
import { act, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

const {
  discussReport,
  invalidateQueries,
  setQueryData,
  useDiscussReport,
  useReportTasks,
} = vi.hoisted(() => ({
  discussReport: vi.fn(),
  invalidateQueries: vi.fn(),
  setQueryData: vi.fn(),
  useDiscussReport: vi.fn(),
  useReportTasks: vi.fn(),
}));

vi.mock("@tanstack/react-query", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@tanstack/react-query")>();
  return {
    ...actual,
    useQueryClient: () => ({ invalidateQueries, setQueryData }),
  };
});

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

vi.mock("@posthog/ui/features/inbox/hooks/useDiscussReport", () => ({
  useDiscussReport,
}));

vi.mock("@posthog/ui/features/canvas/hooks/useTaskChannels", () => ({
  useTaskChannels: () => ({
    generalChannel: { id: "general-channel" },
    isLoading: false,
  }),
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

const report: SignalReport = {
  id: "report-1",
  title: "Some report",
  summary: "A report summary",
  status: "ready",
  total_weight: 1,
  signal_count: 1,
  created_at: "2026-08-26T00:00:00.000Z",
  updated_at: "2026-08-26T00:00:00.000Z",
  artefact_count: 1,
  actionability: "not_actionable",
  implementation_pr_url: null,
  implementation_pr_merged: false,
};

const task: Task = {
  id: "task-1",
  task_number: 1,
  slug: "task-1",
  title: "Discuss report",
  description: "",
  created_at: "2026-08-26T00:00:00.000Z",
  updated_at: "2026-08-26T00:00:00.000Z",
  origin_product: "signals",
};

const discussionTask = {
  task,
  purpose: "discussion",
  purposeLabel: "Discussion",
  startedAt: "2026-08-26T00:00:00.000Z",
} satisfies ReportTaskData;

describe("ReportVerdictBanner", () => {
  let onDiscussionCreated: ((task: Task) => void) | undefined;

  beforeEach(() => {
    useReportChatPanelStore.setState({
      open: false,
      startedTaskIdByReport: {},
    });
    useReportTasks.mockReturnValue({ data: [], isLoading: false });
    discussReport.mockReset();
    discussReport.mockResolvedValue(undefined);
    invalidateQueries.mockReset();
    setQueryData.mockReset();
    onDiscussionCreated = undefined;
    useDiscussReport.mockImplementation(
      (options: { onTaskCreated?: (task: Task) => void }) => {
        onDiscussionCreated = options.onTaskCreated;
        return { discussReport, isDiscussing: false };
      },
    );
  });

  it("starts a discussion with optional direction and hides the actions after creation", async () => {
    const user = userEvent.setup();
    render(<ReportVerdictBanner report={report} initialEngagementOnly />);

    const askButton = screen.getByText("Ask about it");
    expect(askButton.closest(".select-none")).not.toBeNull();

    await user.click(askButton);
    await user.type(
      screen.getByLabelText("Optional question for the agent"),
      "Focus on whether this affects new projects",
    );
    await user.click(screen.getByText("Start chat"));

    expect(discussReport).toHaveBeenCalledWith(
      "Focus on whether this affects new projects",
    );
    expect(screen.getByText("Ask about it")).toBeInTheDocument();

    act(() => onDiscussionCreated?.(discussionTask.task));

    expect(screen.queryByText("Ask about it")).not.toBeInTheDocument();
    expect(setQueryData).toHaveBeenCalled();
    expect(
      useReportChatPanelStore.getState().startedTaskIdByReport[report.id],
    ).toBe(discussionTask.task.id);
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
