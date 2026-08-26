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

    const openButton = screen.getByLabelText("Open existing chat");
    expect(
      openButton.querySelector('[data-slot="conversation-indicator"]'),
    ).toHaveClass("absolute", "-top-1", "-right-1", "bg-(--blue-9)");
    expect(openButton.querySelector('[data-slot="chat-icon"]')).toHaveClass(
      "absolute",
      "inset-0",
      "items-center",
      "justify-center",
    );
    expect(openButton.querySelector('[data-slot="dot"]')).toBeNull();
    expect(openButton).not.toHaveTextContent("Chat");
    expect(openButton).toHaveAttribute("aria-pressed", "false");

    await user.click(openButton);

    expect(screen.getByLabelText("Close chat")).toHaveAttribute(
      "aria-pressed",
      "true",
    );
  });
});
