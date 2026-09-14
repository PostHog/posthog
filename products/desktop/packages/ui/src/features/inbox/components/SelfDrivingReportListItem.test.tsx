import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { inboxStoryReport } from "./inboxStoryFixtures";
import { SelfDrivingReportListItem } from "./SelfDrivingReportListItem";

describe("SelfDrivingReportListItem", () => {
  it.each([
    ["without a pull request", {}, "No PR"],
    [
      "with an open pull request",
      { implementation_pr_url: "https://github.com/PostHog/posthog/pull/12" },
      "#12",
    ],
    [
      "with a draft pull request",
      {
        implementation_pr_url: "https://github.com/PostHog/posthog/pull/12",
        implementation_pr_state: "draft",
      },
      "#12 draft",
    ],
    [
      "with a shipped pull request",
      {
        implementation_pr_url: "https://github.com/PostHog/posthog/pull/12",
        implementation_pr_merged: true,
        status: "resolved",
      },
      "#12 shipped",
    ],
  ] as const)("renders the indicator %s", (_case, overrides, indicator) => {
    const report = inboxStoryReport({
      title: "fix(inbox): render report metadata",
      summary: "The report headline appears in the detail row. More follows.",
      ...overrides,
    });

    render(
      <SelfDrivingReportListItem report={report} showKind onClick={vi.fn()} />,
    );

    const row = screen.getByRole("button", {
      name: "Render report metadata, priority P1, Self-driving report",
    });
    expect(row).toHaveTextContent(indicator);
    expect(row).toHaveTextContent(
      "The report headline appears in the detail row.",
    );
    if (indicator === "#12") {
      expect(row).toHaveTextContent("PostHog/posthog");
    }
  });
});
