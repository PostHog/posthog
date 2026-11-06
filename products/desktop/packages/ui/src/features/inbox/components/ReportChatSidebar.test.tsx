import type { SignalReport, Task } from "@posthog/shared/types";
import { render, screen } from "@testing-library/react";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const { findContinuableImplementationTask, useQuery, useReportTasks } =
  vi.hoisted(() => ({
    findContinuableImplementationTask: vi.fn(),
    useQuery: vi.fn(),
    useReportTasks: vi.fn(),
  }));

vi.mock("@tanstack/react-query", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@tanstack/react-query")>();
  return {
    ...actual,
    useQuery,
    useQueryClient: () => ({
      setQueryData: vi.fn(),
      invalidateQueries: vi.fn(),
    }),
  };
});

vi.mock("@posthog/ui/features/inbox/hooks/useReportTasks", () => ({
  findContinuableImplementationTask,
  findLatestDiscussionTask: () => null,
  findPendingStartedTaskId: () => null,
  useReportTasks,
}));

vi.mock("@posthog/ui/features/canvas/hooks/useTaskChannels", () => ({
  useTaskChannels: () => ({ generalChannel: null }),
}));

vi.mock("@posthog/ui/features/inbox/hooks/useDiscussReport", () => ({
  useDiscussReport: () => ({ discussReport: vi.fn(), isDiscussing: false }),
}));

vi.mock("@posthog/ui/features/inbox/hooks/useReportActionTracker", () => ({
  useReportActionTracker: () => vi.fn(),
}));

vi.mock("@posthog/ui/router/useOpenTask", () => ({
  useOpenTask: () => vi.fn(),
}));

vi.mock("@posthog/ui/primitives/ResizableSidebar", () => ({
  ResizableSidebar: ({ children }: { children: ReactNode }) => children,
}));

vi.mock("@posthog/ui/features/sessions/components/EmbeddedSessionView", () => ({
  EmbeddedSessionView: () => <div>Existing conversation</div>,
}));

import { ReportChatSidebar } from "./ReportChatSidebar";

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
  implementation_pr_url: null,
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

const suggestionLabels = [
  "Fix this issue",
  "Investigate further",
  "Visualize in a Canvas",
  "Continue the fix",
  "Continue the analysis",
];

describe("ReportChatSidebar", () => {
  beforeEach(() => {
    findContinuableImplementationTask.mockReturnValue(null);
    useQuery.mockReturnValue({ data: null });
    useReportTasks.mockReturnValue({ data: [], isLoading: false });
  });

  it("starts with only report context and a question composer", () => {
    render(<ReportChatSidebar report={report} />);

    expect(
      screen.getByLabelText("Question about this report"),
    ).toBeInTheDocument();
    expect(
      screen.getByText(/full report and its evidence already in context/),
    ).toBeInTheDocument();
    for (const label of suggestionLabels) {
      expect(screen.queryByText(label)).not.toBeInTheDocument();
    }
  });

  it("does not add report action suggestions below an existing conversation", () => {
    findContinuableImplementationTask.mockReturnValue(task);
    useQuery.mockReturnValue({ data: task });
    useReportTasks.mockReturnValue({ data: [task], isLoading: false });

    render(<ReportChatSidebar report={report} />);

    expect(screen.getByText("Existing conversation")).toBeInTheDocument();
    for (const label of suggestionLabels) {
      expect(screen.queryByText(label)).not.toBeInTheDocument();
    }
  });
});
