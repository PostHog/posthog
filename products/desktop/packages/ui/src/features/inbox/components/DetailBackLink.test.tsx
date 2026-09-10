import type { SignalReport } from "@posthog/shared/types";
import { ReportPageContext } from "@posthog/ui/features/inbox/components/ReportPageContext";
import { render } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({
  sourceHref: undefined as string | undefined,
  triageOrigin: null as { reportId: string } | null,
  locationState: {} as Record<string, unknown>,
}));

vi.mock("@tanstack/react-router", () => ({
  useLocation: ({ select }: { select: (location: unknown) => unknown }) =>
    select({ state: mocks.locationState }),
  Link: ({
    to,
    state,
  }: {
    to: string;
    state?: ((previous: unknown) => unknown) | undefined;
  }) => (
    <a
      href={to}
      data-state={state ? JSON.stringify(state(mocks.locationState)) : ""}
    >
      {to}
    </a>
  ),
  useRouterState: ({ select }: { select: (state: unknown) => unknown }) =>
    select({
      location: {
        pathname: "/reports/report-1",
        href: "/reports/report-1",
        search: { from: mocks.sourceHref },
        state: mocks.locationState,
      },
    }),
}));

vi.mock("@posthog/ui/features/canvas/hooks/useChannels", () => ({
  useChannels: () => ({ channels: [] }),
}));

import { DetailBackLink } from "./DetailBackLink";

const report = {
  id: "report-1",
  title: "Billing report",
  status: "ready",
} as SignalReport;

describe("DetailBackLink", () => {
  beforeEach(() => {
    mocks.sourceHref = "/inbox/reports";
    mocks.triageOrigin = null;
    mocks.locationState = { inboxTriageOrigin: { reportId: "report-1" } };
  });

  const renderCrumbs = () => {
    const { container } = render(
      <ReportPageContext value={report}>
        <DetailBackLink to="/inbox/reports" label="Self-driving" />
      </ReportPageContext>,
    );
    return container.querySelectorAll("a");
  };

  it("carries the triage origin on the Reports-list crumb", () => {
    mocks.triageOrigin = { reportId: "report-1" };
    const crumb = renderCrumbs()[0];
    expect(crumb?.getAttribute("href")).toBe("/inbox/reports");
    expect(JSON.parse(crumb?.getAttribute("data-state") ?? "{}")).toEqual({
      inboxTriageOrigin: { reportId: "report-1" },
    });
  });

  it("keeps other history state on the triage crumb", () => {
    mocks.triageOrigin = { reportId: "report-1" };
    mocks.locationState = {
      tabId: "tab-1",
      inboxTriageOrigin: { reportId: "report-1" },
    };
    const crumb = renderCrumbs()[0];
    expect(JSON.parse(crumb?.getAttribute("data-state") ?? "{}")).toEqual({
      tabId: "tab-1",
      inboxTriageOrigin: { reportId: "report-1" },
    });
  });

  it("leaves the crumb stateless outside triage", () => {
    mocks.locationState = {};
    const crumb = renderCrumbs()[0];
    expect(crumb?.getAttribute("data-state")).toBe("");
  });

  it("passes no state updater for a settings source", () => {
    mocks.sourceHref = "/settings/agents?agent=scout-1";
    // Category crumb, then agent crumb, both stateless.
    const crumbs = renderCrumbs();
    expect(crumbs).toHaveLength(2);
    for (const crumb of crumbs)
      expect(crumb?.getAttribute("data-state")).toBe("");
    // The agent crumb links to the full settings href, agent included.
    expect(crumbs[1]?.getAttribute("href")).toBe(
      "/settings/agents?agent=scout-1",
    );
  });
});
