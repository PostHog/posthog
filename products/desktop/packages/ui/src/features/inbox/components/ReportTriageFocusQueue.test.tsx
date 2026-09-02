import type { InboxScope } from "@posthog/core/inbox/reportMembership";
import type { SignalReport } from "@posthog/shared/types";
import { render, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({
  bulkActions: {
    removeReviewerDisabledReason: null as string | null,
    isRemovingReviewer: false,
    removeReviewerSelected: vi.fn(
      (): Promise<{ succeededIds: string[] } | null> =>
        Promise.resolve({ succeededIds: [] }),
    ),
    isSuppressing: false,
    isSnoozing: false,
    snoozeDisabledReason: null as string | null,
    suppressSelected: vi.fn(() => Promise.resolve(true)),
    snoozeSelected: vi.fn(() => Promise.resolve(true)),
  },
  viewProps: null as Record<string, unknown> | null,
  toastWarning: vi.fn(),
}));

vi.mock("@posthog/ui/features/inbox/hooks/useInboxBulkActions", () => ({
  useInboxBulkActions: () => mocks.bulkActions,
}));

vi.mock("@posthog/ui/features/inbox/hooks/useReportTasks", () => ({
  useReportTasks: () => ({ data: [], isLoading: false }),
  findContinuableImplementationTask: () => null,
  getTaskPrUrl: () => null,
}));

vi.mock(
  "@posthog/ui/features/inbox/hooks/useInboxReportDetailPrefetch",
  () => ({
    useInboxReportDetailPrefetch: () => ({ prefetch: vi.fn() }),
  }),
);

vi.mock("@posthog/ui/router/navigationBridge", () => ({
  navigateToInboxReportDetail: vi.fn(),
}));

vi.mock("@posthog/ui/shell/analytics", () => ({
  track: vi.fn(),
}));

vi.mock("@posthog/ui/primitives/toast", () => ({
  toast: {
    success: vi.fn(),
    error: vi.fn(),
    info: vi.fn(),
    warning: mocks.toastWarning,
    loading: vi.fn(),
    dismiss: vi.fn(),
  },
}));

vi.mock("@posthog/ui/features/inbox/components/ReportTriageFocusView", () => ({
  ReportTriageFocusView: (props: Record<string, unknown>) => {
    mocks.viewProps = props;
    return null;
  },
}));

vi.mock("@posthog/ui/features/inbox/components/ReportVerdictBanner", () => ({
  ReportVerdictBanner: () => null,
}));

vi.mock(
  "@posthog/ui/features/inbox/components/SuggestedReviewerAvatarStack",
  () => ({ SuggestedReviewerAvatarStack: () => null }),
);

vi.mock("@posthog/ui/features/inbox/components/ReportChatSidebar", () => ({
  ReportChatSidebar: () => null,
}));

vi.mock("@posthog/ui/features/inbox/components/DismissReportDialog", () => ({
  DismissReportDialog: () => null,
}));

import { ReportTriageFocus } from "./ReportTriageFocus";

function report(id: string): SignalReport {
  return {
    id,
    title: `Report ${id}`,
    summary: null,
    status: "ready",
    total_weight: 1,
    signal_count: 1,
    created_at: "2026-01-01T00:00:00Z",
    updated_at: "2026-01-01T00:00:00Z",
    artefact_count: 0,
    implementation_pr_url: null,
    actionability: "immediately_actionable",
    is_suggested_reviewer: true,
  };
}

function renderTriage(
  reports: SignalReport[],
  scope: InboxScope = "for-you",
): { onExit: ReturnType<typeof vi.fn> } {
  const onExit = vi.fn();
  render(
    <ReportTriageFocus
      reports={reports}
      allReports={reports}
      scope={scope}
      hasActiveFilters={false}
      onExit={onExit}
    />,
  );
  return { onExit };
}

async function pressR(): Promise<void> {
  await userEvent.keyboard("r");
}

async function pressArrowDown(): Promise<void> {
  await userEvent.keyboard("{ArrowDown}");
}

describe("ReportTriageFocus queue behavior on remove-reviewer", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mocks.viewProps = null;
    mocks.bulkActions.isRemovingReviewer = false;
    mocks.bulkActions.removeReviewerSelected.mockReset();
  });

  it("shows the report after the removed one (queue-shrink advance)", async () => {
    const reports = [report("a"), report("b"), report("c")];
    mocks.bulkActions.removeReviewerSelected.mockResolvedValue({
      succeededIds: ["a"],
    });
    renderTriage(reports);

    await pressR();

    await waitFor(() =>
      expect((mocks.viewProps?.report as SignalReport).id).toBe("b"),
    );
  });

  it("never skips the next report when the user navigates while removal is pending", async () => {
    const reports = [report("a"), report("b"), report("c")];
    let settle: (result: { succeededIds: string[] }) => void = () => {};
    mocks.bulkActions.removeReviewerSelected.mockImplementation(
      () =>
        new Promise((resolve) => {
          settle = resolve;
        }),
    );
    renderTriage(reports);

    await pressR();
    await pressArrowDown();
    expect((mocks.viewProps?.report as SignalReport).id).toBe("c");

    settle({ succeededIds: ["a"] });
    await waitFor(() =>
      expect((mocks.viewProps?.report as SignalReport).id).toBe("c"),
    );
  });

  it("offers a jump back to the report when the removal fails", async () => {
    const reports = [report("a"), report("b"), report("c")];
    let settle: (result: { succeededIds: string[] }) => void = () => {};
    mocks.bulkActions.removeReviewerSelected.mockImplementation(
      () =>
        new Promise((resolve) => {
          settle = resolve;
        }),
    );
    renderTriage(reports);

    await pressR();
    await pressArrowDown();
    settle({ succeededIds: [] });

    await waitFor(() => expect(mocks.toastWarning).toHaveBeenCalledOnce());
    const [, options] = mocks.toastWarning.mock.calls[0] as [
      string,
      { action: { label: string; onClick: () => void } },
    ];
    expect(options.action.label).toBe("Back to report");

    options.action.onClick();
    await waitFor(() =>
      expect((mocks.viewProps?.report as SignalReport).id).toBe("a"),
    );
  });

  it("keeps the report in the queue in entire-project scope", async () => {
    const reports = [report("a"), report("b"), report("c")];
    mocks.bulkActions.removeReviewerSelected.mockResolvedValue({
      succeededIds: ["a"],
    });
    renderTriage(reports, "entire-project");

    await pressR();

    await waitFor(() => expect(mocks.viewProps?.total).toBe(3));
    expect((mocks.viewProps?.report as SignalReport).id).toBe("a");
  });
});
