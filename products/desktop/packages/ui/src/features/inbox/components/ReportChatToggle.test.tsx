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

import { ReportChatToggle } from "./ReportChatToggle";

const report = {
  id: "report-1",
  status: "ready",
} as SignalReport;

const discussionTask = {
  task: { id: "task-1" } as Task,
  purpose: "discussion",
  purposeLabel: "Discussion",
  startedAt: "2026-08-26T00:00:00.000Z",
};

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

    const openButton = screen.getByLabelText(
      "Open chat (existing conversation)",
    );
    expect(openButton.querySelector('[data-slot="dot"]')).not.toBeNull();
    expect(openButton).toHaveAttribute("aria-pressed", "false");

    await user.click(openButton);

    expect(
      screen.getByLabelText("Close chat (existing conversation)"),
    ).toHaveAttribute("aria-pressed", "true");
  });
});
