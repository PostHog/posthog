import type { SignalReport, Task } from "@posthog/shared/types";
import type { ReportTaskData } from "@posthog/ui/features/inbox/hooks/useReportTasks";
import { useReportChatPanelStore } from "@posthog/ui/features/inbox/stores/reportChatPanelStore";
import { act, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

const {
  createPrReport,
  discussReport,
  invalidateQueries,
  openExternalUrl,
  openTaskInput,
  openTask,
  setQueryData,
  useDiscussReport,
  useReportTasks,
  useInboxReportArtefacts,
  openResolveDialog,
} = vi.hoisted(() => ({
  createPrReport: vi.fn(),
  discussReport: vi.fn(),
  invalidateQueries: vi.fn(),
  openExternalUrl: vi.fn(),
  openTaskInput: vi.fn(),
  openTask: vi.fn(),
  setQueryData: vi.fn(),
  useDiscussReport: vi.fn(),
  useReportTasks: vi.fn(),
  useInboxReportArtefacts: vi.fn(),
  openResolveDialog: vi.fn(),
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
  useCreatePrReport: () => ({ createPrReport, isCreatingPr: false }),
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

vi.mock("@posthog/ui/features/inbox/hooks/useInboxReportDismissAction", () => ({
  useInboxReportDismissAction: () => ({
    dialog: null,
    openDialog: vi.fn(),
  }),
}));

vi.mock("@posthog/ui/features/inbox/hooks/useInboxReportResolveAction", () => ({
  useInboxReportResolveAction: () => ({
    dialog: null,
    isPending: false,
    openDialog: openResolveDialog,
  }),
}));

vi.mock("@posthog/ui/features/inbox/hooks/useInboxReports", () => ({
  useInboxReportArtefacts,
}));

vi.mock("@posthog/ui/features/inbox/hooks/useReportActionTracker", () => ({
  useReportActionTracker: () => vi.fn(),
}));

vi.mock("@posthog/ui/router/useOpenTask", () => ({
  openTaskInput,
  useOpenTask: () => openTask,
}));

vi.mock("@posthog/ui/shell/openExternal", () => ({
  openExternalUrl,
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

const runningImplementationTask = {
  task: {
    ...task,
    title: "Implement fix",
    latest_run: {
      id: "run-1",
      status: "in_progress",
      output: null,
    } as Task["latest_run"],
  },
  purpose: "implementation",
  purposeLabel: "Implementation",
  startedAt: "2026-08-26T00:00:00.000Z",
} satisfies ReportTaskData;

const repoArtefacts = {
  count: 1,
  results: [
    {
      id: "repo-selection-1",
      type: "repo_selection",
      created_at: "2026-08-26T00:00:00.000Z",
      content: {
        repository: "PostHog/posthog",
        reason: "The report concerns this repository.",
      },
    },
  ],
};

describe("ReportVerdictBanner", () => {
  let onDiscussionCreated: ((task: Task) => void) | undefined;

  beforeEach(() => {
    useReportChatPanelStore.setState({
      open: false,
      startedTaskIdByReport: {},
    });
    useReportTasks.mockReturnValue({ data: [], isLoading: false });
    useInboxReportArtefacts.mockReturnValue({
      data: repoArtefacts,
      isLoading: false,
    });
    createPrReport.mockReset();
    discussReport.mockReset();
    discussReport.mockResolvedValue(undefined);
    invalidateQueries.mockReset();
    openExternalUrl.mockReset();
    openTaskInput.mockReset();
    openTask.mockReset();
    openResolveDialog.mockReset();
    setQueryData.mockReset();
    onDiscussionCreated = undefined;
    useDiscussReport.mockImplementation(
      (options: { onTaskCreated?: (task: Task) => void }) => {
        onDiscussionCreated = options.onTaskCreated;
        return { discussReport, isDiscussing: false };
      },
    );
  });

  it("offers resolve in triage from both the button and shortcut", async () => {
    const user = userEvent.setup();
    render(
      <ReportVerdictBanner
        report={report}
        variant="triage-actions"
        resolveHotkey="r"
      />,
    );

    await user.click(screen.getByText("Resolve"));
    await user.keyboard("r");

    expect(openResolveDialog).toHaveBeenCalledTimes(2);
    expect(screen.getByText("Dismiss")).toBeInTheDocument();
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

  it.each([
    ["ready", "immediately_actionable"],
    ["ready", "requires_human_input"],
    ["pending_input", "requires_human_input"],
  ] as const)(
    "opens the task composer for a %s report that is %s",
    async (status, actionability) => {
      const user = userEvent.setup();
      render(
        <ReportVerdictBanner report={{ ...report, status, actionability }} />,
      );

      expect(screen.queryByText("Create PR")).not.toBeInTheDocument();
      await user.click(screen.getByText("Implement"));

      expect(openTaskInput).toHaveBeenCalledWith({
        initialPrompt: "Implement the recommended next step in this report.",
        initialCloudRepository: "PostHog/posthog",
        reportAssociation: {
          reportId: report.id,
          title: report.title,
        },
      });
      expect(createPrReport).not.toHaveBeenCalled();
    },
  );

  it("waits for the report repository before opening the task composer", async () => {
    const user = userEvent.setup();
    useInboxReportArtefacts.mockReturnValue({
      data: undefined,
      isLoading: true,
    });
    const actionableReport = {
      ...report,
      actionability: "immediately_actionable" as const,
    };
    const { rerender } = render(
      <ReportVerdictBanner report={actionableReport} />,
    );

    const implementLabel = screen.getByText("Implement");
    expect(implementLabel.closest("button")).toHaveAttribute(
      "aria-disabled",
      "true",
    );
    await user.click(implementLabel);
    expect(openTaskInput).not.toHaveBeenCalled();

    useInboxReportArtefacts.mockReturnValue({
      data: repoArtefacts,
      isLoading: false,
    });
    rerender(<ReportVerdictBanner report={actionableReport} />);

    await user.click(screen.getByText("Implement"));
    expect(openTaskInput).toHaveBeenCalledWith(
      expect.objectContaining({
        initialCloudRepository: "PostHog/posthog",
      }),
    );
  });

  it("opens the task composer when the report selected no repository", async () => {
    const user = userEvent.setup();
    useInboxReportArtefacts.mockReturnValue({
      data: { count: 0, results: [] },
      isLoading: false,
    });
    render(
      <ReportVerdictBanner
        report={{
          ...report,
          status: "pending_input",
          actionability: "requires_human_input",
        }}
      />,
    );

    await user.click(screen.getByText("Implement"));

    expect(openTaskInput).toHaveBeenCalledWith(
      expect.objectContaining({ initialCloudRepository: undefined }),
    );
  });

  it("uses the PR shortcut to open an existing PR", async () => {
    const user = userEvent.setup();
    render(
      <ReportVerdictBanner
        report={{
          ...report,
          implementation_pr_url: "https://github.com/PostHog/posthog/pull/1",
        }}
        prHotkey="c"
      />,
    );

    expect(screen.getByText("View PR on GitHub")).toBeInTheDocument();
    expect(screen.getByText("Ask about it")).toBeInTheDocument();
    expect(screen.queryByText("Continue the task")).not.toBeInTheDocument();
    expect(screen.queryByText("Create PR")).not.toBeInTheDocument();
    expect(screen.queryByText("Defer")).not.toBeInTheDocument();

    await user.keyboard("c");

    expect(openExternalUrl).toHaveBeenCalledWith(
      "https://github.com/PostHog/posthog/pull/1",
    );
  });

  it("does not use the PR shortcut for running work without a PR", async () => {
    const user = userEvent.setup();
    useReportTasks.mockReturnValue({
      data: [runningImplementationTask],
      isLoading: false,
    });

    render(
      <ReportVerdictBanner
        report={{ ...report, actionability: "immediately_actionable" }}
        prHotkey="c"
      />,
    );

    expect(screen.getByText("View task")).toBeInTheDocument();
    expect(screen.getByText("Ask about it")).toBeInTheDocument();
    expect(screen.queryByText("Create PR")).not.toBeInTheDocument();

    await user.keyboard("c");

    expect(openTask).not.toHaveBeenCalled();
    expect(createPrReport).not.toHaveBeenCalled();
  });

  it("withholds Create PR when the task lookup failed", () => {
    // An unresolved lookup cannot rule out live implementation work, so offering
    // Create PR here would bill a second agent PR on work that already has one.
    useReportTasks.mockReturnValue({
      data: undefined,
      isLoading: false,
      isError: true,
    });

    render(
      <ReportVerdictBanner
        report={{ ...report, actionability: "immediately_actionable" }}
        variant="triage-actions"
        surface="triage"
      />,
    );

    expect(screen.queryByText("Create PR")).not.toBeInTheDocument();
  });

  it("keeps triage direction before creating the implementation task", async () => {
    const user = userEvent.setup();
    render(
      <ReportVerdictBanner
        report={{ ...report, actionability: "immediately_actionable" }}
        variant="triage-actions"
        prHotkey="c"
        surface="triage"
      />,
    );

    expect(screen.queryByText("Ask about it")).not.toBeInTheDocument();

    await user.keyboard("c");

    const direction = screen.getByLabelText("Optional direction for the agent");
    expect(direction).toBeInTheDocument();
    expect(createPrReport).not.toHaveBeenCalled();

    await user.type(direction, "Start with the smallest safe change");
    await user.click(screen.getAllByText("Create PR")[1]);

    expect(createPrReport).toHaveBeenCalledWith(
      "Start with the smallest safe change",
    );
  });
});
