import type { SignalReport, Task } from "@posthog/shared/types";
import type { ReportTaskData } from "@posthog/ui/features/inbox/hooks/useReportTasks";
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

import { ReportChatToggle } from "./ReportChatToggle";

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

describe("ReportChatToggle", () => {
  beforeEach(() => {
    useReportChatPanelStore.setState({
      open: false,
      startedTaskIdByReport: {},
    });
    useReportTasks.mockReturnValue({ data: [discussionTask] });
  });

  it("toggles chat and marks a report with an existing conversation", async () => {
    const user = userEvent.setup();
    render(<ReportChatToggle report={report} />);

    const openButton = screen.getByLabelText("Open existing chat");
    expect(
      openButton.querySelector('[data-slot="conversation-indicator"]'),
    ).toBeInTheDocument();
    expect(
      openButton.querySelector('[data-slot="chat-icon"]'),
    ).toBeInTheDocument();
    expect(openButton).not.toHaveTextContent("Chat");
    expect(openButton).toHaveAttribute("aria-pressed", "false");

    await user.click(openButton);

    expect(screen.getByLabelText("Close chat")).toHaveAttribute(
      "aria-pressed",
      "true",
    );
  });
});
