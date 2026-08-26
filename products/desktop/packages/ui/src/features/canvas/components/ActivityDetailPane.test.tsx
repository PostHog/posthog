import type { SignalReport } from "@posthog/shared/types";
import { render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({
  reports: [] as SignalReport[],
  selection: null as { kind: "report"; id: string; reportId: string } | null,
}));

vi.mock("@posthog/ui/features/canvas/hooks/useChannels", () => ({
  useChannels: () => ({ channels: [] }),
}));
vi.mock("@posthog/ui/features/canvas/hooks/useInboxActivityPreview", () => ({
  useInboxActivityPreview: () => ({ reports: mocks.reports }),
}));
vi.mock("@posthog/ui/features/canvas/stores/activityDetailStore", () => ({
  useActivitySelection: () => mocks.selection,
}));
vi.mock("@posthog/ui/features/tasks/useResolvedTask", () => ({
  useResolvedTask: () => undefined,
}));
vi.mock("@posthog/ui/features/task-detail/components/TaskDetail", () => ({
  TaskDetail: () => <div>Task detail</div>,
}));
vi.mock("@posthog/ui/router/routeSkeletons", () => ({
  TaskDetailSkeleton: () => <div>Task loading</div>,
}));
vi.mock("@posthog/ui/features/inbox/components/ReportDetail", () => ({
  ReportDetail: ({
    reportId,
    cachedReport,
    statusRedirect,
  }: {
    reportId: string;
    cachedReport?: SignalReport;
    statusRedirect?: boolean;
  }) => (
    <div data-testid="report-detail">
      {reportId}:{cachedReport?.title}:
      {statusRedirect === false ? "instant" : "loading"}
    </div>
  ),
}));

import { ActivityDetailPane } from "./ActivityDetailPane";

describe("ActivityDetailPane", () => {
  beforeEach(() => {
    mocks.reports = [];
    mocks.selection = null;
  });

  it("renders a selected feed report immediately from the preview data", () => {
    mocks.selection = {
      kind: "report",
      id: "report-1",
      reportId: "report-1",
    };
    mocks.reports = [
      {
        id: "report-1",
        title: "Checkout conversion dropped",
      } as SignalReport,
    ];

    render(<ActivityDetailPane />);

    expect(screen.getByTestId("report-detail")).toHaveTextContent(
      "report-1:Checkout conversion dropped:instant",
    );
  });
});
