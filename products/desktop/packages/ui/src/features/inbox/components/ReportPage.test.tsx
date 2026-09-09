import type { SignalReport } from "@posthog/shared/types";
import { render, screen } from "@testing-library/react";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({
  report: { id: "report-1", status: "ready" } as SignalReport,
  source: undefined as string | undefined,
  gate: vi.fn(),
  tracker: vi.fn(() => null),
}));

vi.mock("@tanstack/react-router", () => ({
  useRouterState: ({ select }: { select: (state: unknown) => unknown }) =>
    select({
      location: {
        pathname: "/reports/report-1",
        href: "/reports/report-1",
        search: { from: mocks.source },
      },
    }),
}));

vi.mock("@posthog/ui/features/inbox/components/InboxReportDetailGate", () => ({
  InboxReportDetailGate: (props: {
    children: (report: SignalReport) => ReactNode;
  }) => {
    mocks.gate(props);
    return props.children(mocks.report);
  },
  ReportOpenTracker: mocks.tracker,
}));

vi.mock("@posthog/ui/features/settings/components/SettingsLayout", () => ({
  SettingsLayout: ({
    category,
    children,
  }: {
    category: string;
    children: ReactNode;
  }) => <section aria-label={`Settings ${category}`}>{children}</section>,
}));

vi.mock("@posthog/ui/features/inbox/components/ReportDetail", () => ({
  ReportDetailContent: () => <div>Report content</div>,
}));

vi.mock("@posthog/ui/features/inbox/components/PullRequestDetail", () => ({
  PullRequestDetailContent: () => <div>PR content</div>,
}));

vi.mock("@posthog/ui/features/inbox/components/DismissedReportDetail", () => ({
  DismissedReportDetailContent: () => <div>Archived content</div>,
}));

import { ReportPage } from "./ReportPage";

describe("ReportPage", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mocks.source = undefined;
    mocks.report = { id: "report-1", status: "ready" } as SignalReport;
  });

  it.each([
    ["/settings/agents", "Settings agents"],
    ["/settings/agents?agent=account-mrr", "Settings agents"],
    ["/spaces/space-1", null],
    [undefined, null],
  ])("renders a report from %s inside %s", (source, region) => {
    mocks.source = source;
    render(<ReportPage reportId="report-1" cachedReport={null} />);
    expect(screen.getByText("Report content")).toBeInTheDocument();
    if (region) {
      expect(screen.getByRole("region", { name: region })).toBeInTheDocument();
    } else {
      expect(screen.queryByRole("region")).not.toBeInTheDocument();
    }
  });

  it.each([
    ["/settings/agents", "/settings/agents", "Agents"],
    ["/spaces/space-1", "/spaces/space-1", "Spaces"],
    [undefined, "/inbox/reports", "Self-driving"],
  ])(
    "points the missing-report link at the origin %s",
    (source, backLinkTo, backLabel) => {
      mocks.source = source;
      render(<ReportPage reportId="report-1" cachedReport={null} />);
      expect(screen.getByText("Report content")).toBeInTheDocument();
      expect(mocks.gate).toHaveBeenCalledWith(
        expect.objectContaining({ backLinkTo, backLabel, backTo: "/" }),
      );
    },
  );

  it.each(["suppressed", "resolved"] as const)(
    "renders %s reports read-only even with a PR",
    (status) => {
      mocks.report = {
        ...mocks.report,
        status,
        implementation_pr_url: "https://github.com/example/repo/pull/1",
      };
      render(<ReportPage reportId="report-1" cachedReport={null} />);
      expect(screen.getByText("Archived content")).toBeInTheDocument();
      expect(screen.queryByText("PR content")).not.toBeInTheDocument();
      expect(mocks.tracker).not.toHaveBeenCalled();
    },
  );

  it("changes content in place as a report gains a PR, archives, and restores", () => {
    mocks.source = "/settings/agents";
    const { rerender } = render(
      <ReportPage reportId="report-1" cachedReport={null} />,
    );
    expect(screen.getByText("Report content")).toBeInTheDocument();
    mocks.report = {
      ...mocks.report,
      implementation_pr_url: "https://github.com/example/repo/pull/1",
    };
    rerender(<ReportPage reportId="report-1" cachedReport={null} />);
    expect(screen.getByText("PR content")).toBeInTheDocument();
    mocks.report = { ...mocks.report, status: "suppressed" };
    rerender(<ReportPage reportId="report-1" cachedReport={null} />);
    expect(screen.getByText("Archived content")).toBeInTheDocument();
    mocks.report = { ...mocks.report, status: "ready" };
    rerender(<ReportPage reportId="report-1" cachedReport={null} />);
    expect(screen.getByText("PR content")).toBeInTheDocument();
    for (const [props] of mocks.gate.mock.calls)
      expect(props.statusRedirect).toBe(false);
  });
});
