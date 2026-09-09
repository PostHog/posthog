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
        state: { reportSourceHref: mocks.source },
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

vi.mock("@posthog/ui/features/inbox/components/ReportDetail", () => ({
  ReportDetailContent: () => <div>Report content</div>,
}));

vi.mock("@posthog/ui/features/inbox/components/PullRequestDetail", () => ({
  PullRequestDetailContent: () => <div>PR content</div>,
}));

vi.mock("@posthog/ui/features/inbox/components/DismissedReportDetail", () => ({
  DismissedReportDetailContent: () => <div>Archived content</div>,
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

import { ReportPage } from "./ReportPage";

describe("ReportPage", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mocks.source = undefined;
    mocks.report = { id: "report-1", status: "ready" } as SignalReport;
  });

  it("uses the Settings layout for reports opened from Agents", () => {
    mocks.source = "/settings/agents";
    render(<ReportPage reportId="report-1" cachedReport={null} />);
    expect(
      screen.getByRole("region", { name: "Settings agents" }),
    ).toHaveTextContent("Report content");
    expect(mocks.gate).toHaveBeenCalledWith(
      expect.objectContaining({
        statusRedirect: false,
        backLinkTo: "/settings/agents",
        backLabel: "Back",
      }),
    );
  });

  it("renders direct links without Settings navigation or an Inbox parent", () => {
    render(<ReportPage reportId="report-1" cachedReport={null} />);
    expect(screen.queryByRole("region")).not.toBeInTheDocument();
    expect(mocks.gate).toHaveBeenCalledWith(
      expect.objectContaining({
        backTo: "/",
        statusRedirect: false,
      }),
    );
  });

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
    expect(
      screen.getByRole("region", { name: "Settings agents" }),
    ).toHaveTextContent("PR content");
    for (const [props] of mocks.gate.mock.calls)
      expect(props.statusRedirect).toBe(false);
  });
});
