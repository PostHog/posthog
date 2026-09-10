import type { SignalReport } from "@posthog/shared/types";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("@posthog/ui/features/inbox/hooks/useInboxReports", () => ({
  useInboxReportArtefacts: () => ({ data: null }),
}));
vi.mock(
  "@posthog/ui/features/inbox/hooks/useInboxReportDetailPrefetch",
  () => ({
    useInboxReportDetailPrefetch: () => ({
      prefetch: vi.fn(),
      pointerHandlers: {},
    }),
  }),
);
// The reviewer stack reaches for the authenticated client, which no test host provides.
vi.mock(
  "@posthog/ui/features/inbox/components/SuggestedReviewerAvatarStack",
  () => ({ SuggestedReviewerAvatarStack: () => null }),
);
vi.mock("@posthog/ui/shell/analytics", () => ({ track: vi.fn() }));
vi.mock("@tanstack/react-router", () => ({
  Link: ({
    children,
    className,
  }: {
    children: React.ReactNode;
    className?: string;
  }) => (
    <a className={className} href="/reports/r1">
      {children}
    </a>
  ),
  useNavigate: () => vi.fn(),
}));

import { ReportCard } from "@posthog/ui/features/inbox/components/ReportCard";
import { useInboxReportSelectionStore } from "@posthog/ui/features/inbox/stores/inboxReportSelectionStore";

const report = {
  id: "r1",
  title: "fix(inbox): a thing",
  summary: "Something happened.",
  status: "ready",
} as unknown as SignalReport;

function selectionCheckbox(): HTMLElement {
  return screen.getByLabelText("Select report: fix(inbox): a thing");
}

describe("ReportCard selection affordance", () => {
  beforeEach(() => {
    useInboxReportSelectionStore.setState({
      selectedReportIds: [],
      lastClickedId: null,
      orderedReportIds: ["r1"],
    });
  });

  it("hides the checkbox behind hover while nothing is selected", () => {
    render(<ReportCard report={report} onDismiss={vi.fn()} />);

    const gutter = selectionCheckbox().parentElement;
    expect(gutter?.className).toContain("group-hover:opacity-100");
    expect(gutter?.className).toContain("opacity-0");
  });

  it("pins the checkbox visible once the list is in selection mode", () => {
    useInboxReportSelectionStore.setState({ selectedReportIds: ["r1"] });
    render(<ReportCard report={report} onDismiss={vi.fn()} />);

    expect(selectionCheckbox().parentElement?.className).not.toContain(
      "opacity-0",
    );
  });

  it("selects the report from the checkbox", async () => {
    render(<ReportCard report={report} onDismiss={vi.fn()} />);

    await userEvent.click(selectionCheckbox());

    expect(useInboxReportSelectionStore.getState().selectedReportIds).toEqual([
      "r1",
    ]);
  });

  it("marks a selected card with a ring rather than opacity alone", () => {
    useInboxReportSelectionStore.setState({ selectedReportIds: ["r1"] });
    const { container } = render(
      <ReportCard report={report} onDismiss={vi.fn()} />,
    );

    expect(container.querySelector(".ring-2")).not.toBeNull();
  });

  it("offers no checkbox on an archived card, which is read-only", () => {
    render(
      <ReportCard variant="archived" report={report} onRestore={vi.fn()} />,
    );

    expect(
      screen.queryByLabelText("Select report: fix(inbox): a thing"),
    ).toBeNull();
  });
});
