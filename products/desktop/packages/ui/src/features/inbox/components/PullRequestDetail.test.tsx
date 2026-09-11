import type { SignalReport } from "@posthog/shared/types";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ReactNode } from "react";
import { useState } from "react";
import { describe, expect, it, vi } from "vitest";
import { PullRequestDetailContent } from "./PullRequestDetail";

vi.mock("./ReportDetail", () => ({
  ReportChatLayout: ({ children }: { children: ReactNode }) => children,
}));
vi.mock("./InboxDetailFrame", () => ({
  InboxDetailFrame: ({
    metaSuffix,
    primaryAction,
    secondaryTab,
    belowSummary,
  }: {
    metaSuffix: ReactNode;
    primaryAction: ReactNode;
    secondaryTab?: { content: ReactNode };
    belowSummary: ReactNode;
  }) => (
    <>
      {metaSuffix}
      {primaryAction}
      {secondaryTab?.content}
      {belowSummary}
    </>
  ),
}));
vi.mock("./ReportDetailActions", () => ({
  ReportDetailActions: ({ prUrl }: { prUrl: string }) => (
    <a href={prUrl}>Open selected PR</a>
  ),
}));
vi.mock("./utils/ReportTrackerIssueLink", () => ({
  ReportTrackerIssueLink: () => null,
}));
vi.mock("@posthog/ui/features/pr-review/PrFilesChangedSection", () => ({
  PrFilesChangedSection: ({ prUrl }: { prUrl: string }) => (
    <a href={`${prUrl}/files`}>Selected files</a>
  ),
}));
vi.mock("@posthog/ui/features/pr-review/PrDecisionBlock", () => ({
  PrDecisionBlock: ({ prUrl }: { prUrl: string }) => (
    <a href={`${prUrl}/checks`}>Selected checks</a>
  ),
}));
vi.mock("@posthog/ui/features/pr-review/PrCommentsSection", () => ({
  PrCommentsSection: ({ prUrl }: { prUrl: string }) => {
    const [draft, setDraft] = useState("");
    return (
      <>
        <a href={prUrl}>Selected comments</a>
        <input
          aria-label="Comment draft"
          value={draft}
          onChange={(event) => setDraft(event.target.value)}
        />
      </>
    );
  },
}));

const first = "https://github.com/example/app/pull/1";
const second = "https://github.com/example/app/pull/2";
const report: SignalReport = {
  id: "report-with-stack",
  title: "Example fix",
  summary: "Synthetic report",
  status: "ready",
  total_weight: 1,
  signal_count: 1,
  artefact_count: 0,
  created_at: "2026-01-01T00:00:00Z",
  updated_at: "2026-01-01T00:00:00Z",
  implementation_pr_url: first,
  pull_requests: [
    {
      id: "one",
      url: first,
      state: "merged",
      merged: true,
      claim_id: null,
      attached_at: null,
      attached_by: null,
    },
    {
      id: "two",
      url: second,
      state: "open",
      merged: false,
      claim_id: null,
      attached_at: null,
      attached_by: null,
    },
  ],
};

describe("report PR selection", () => {
  it("switches every review surface and clears the previous PR's draft", async () => {
    const user = userEvent.setup();
    render(<PullRequestDetailContent report={report} />);
    expect(
      screen.getByRole("link", { name: "Open selected PR" }),
    ).toHaveAttribute("href", second);
    fireEvent.change(screen.getByRole("textbox", { name: "Comment draft" }), {
      target: { value: "Only for PR two" },
    });
    await user.click(screen.getByRole("combobox", { name: "Pull request" }));
    await user.click(
      await screen.findByRole("option", { name: "example/app#1 (merged)" }),
    );
    await waitFor(() =>
      expect(
        screen.getByRole("link", { name: "Open selected PR" }),
      ).toHaveAttribute("href", first),
    );
    expect(
      screen.getByRole("link", { name: "Selected files" }),
    ).toHaveAttribute("href", `${first}/files`);
    expect(
      screen.getByRole("link", { name: "Selected checks" }),
    ).toHaveAttribute("href", `${first}/checks`);
    expect(
      screen.getByRole("link", { name: "Selected comments" }),
    ).toHaveAttribute("href", first);
    expect(screen.getByRole("textbox", { name: "Comment draft" })).toHaveValue(
      "",
    );
  });
});
