import type { SignalReport } from "@posthog/shared/types";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({
  copyLink: vi.fn(),
  createPr: vi.fn(),
  createPrOptions: undefined as
    | { surface?: string; reportId: string }
    | undefined,
  dismissWithReason: vi.fn(),
  openDismissDialog: vi.fn(),
  openResolveDialog: vi.fn(),
  resolveWithReason: vi.fn(),
  restore: vi.fn(),
  trackerSurface: undefined as string | undefined,
  trackAction: vi.fn(),
  actionHooksMounted: 0,
  reportTasks: undefined as
    | { purpose: string; task: { latest_run?: { status?: string } } }[]
    | undefined,
}));

vi.mock("@posthog/ui/features/inbox/hooks/useInboxReportResolveAction", () => ({
  useInboxReportResolveAction: () => {
    mocks.actionHooksMounted += 1;
    return {
      dialog: null,
      isPending: false,
      openDialog: mocks.openResolveDialog,
      resolveWithReason: mocks.resolveWithReason,
    };
  },
}));

vi.mock("@posthog/ui/features/inbox/hooks/useInboxReportDismissAction", () => ({
  useInboxReportDismissAction: () => ({
    actionButton: null,
    dialog: null,
    openDialog: mocks.openDismissDialog,
    dismissWithReason: mocks.dismissWithReason,
  }),
}));

vi.mock("@posthog/ui/features/inbox/hooks/useInboxRestoreReport", () => ({
  useInboxRestoreReport: () => ({
    isPending: false,
    mutate: mocks.restore,
  }),
}));

vi.mock("@posthog/ui/features/inbox/hooks/useCreatePrReport", () => ({
  useCreatePrReport: (options: { surface?: string; reportId: string }) => {
    mocks.createPrOptions = options;
    return {
      createPrReport: mocks.createPr,
      isCreatingPr: false,
    };
  },
}));

vi.mock("@posthog/ui/features/inbox/hooks/useReportTasks", () => ({
  useReportTasks: () => ({
    data: mocks.reportTasks,
    isLoading: false,
    isError: false,
  }),
  findContinuableImplementationTask: (
    tasks: { purpose: string; task: unknown }[] | undefined,
  ) => tasks?.find((entry) => entry.purpose === "implementation")?.task ?? null,
}));

vi.mock("@posthog/ui/features/inbox/hooks/useInboxReports", () => ({
  useInboxReportArtefacts: () => ({ data: { results: [] } }),
}));

vi.mock("@posthog/ui/features/inbox/hooks/useReportActionTracker", () => ({
  useReportActionTracker: (_report: unknown, surface?: string) => {
    mocks.trackerSurface = surface;
    return mocks.trackAction;
  },
}));

vi.mock("@posthog/ui/features/inbox/components/ReviewerSearchList", () => ({
  ReviewerSearchList: () => <div>Reviewer picker</div>,
}));

vi.mock("@posthog/ui/features/inbox/utils/copyInboxReportLink", () => ({
  copyInboxReportLink: mocks.copyLink,
}));

import { InboxReportContextMenu } from "./InboxReportContextMenu";

function makeReport(overrides: Partial<SignalReport> = {}): SignalReport {
  return {
    id: "report-1",
    title: "Report one",
    summary: "Summary",
    status: "ready",
    actionability: "immediately_actionable",
    total_weight: 1,
    signal_count: 1,
    artefact_count: 1,
    created_at: "2026-08-20T09:00:00Z",
    updated_at: "2026-08-20T09:00:00Z",
    ...overrides,
  };
}

function openMenu(report: SignalReport): void {
  render(
    <InboxReportContextMenu report={report}>
      <div>{report.title}</div>
    </InboxReportContextMenu>,
  );
  fireEvent.contextMenu(screen.getByText(report.title ?? ""));
}

function menuItemText(): (string | null)[] {
  return screen.queryAllByRole("menuitem").map((item) => item.textContent);
}

const LINK_ITEMS = ["Copy link"];

describe("InboxReportContextMenu", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mocks.trackerSurface = undefined;
    mocks.createPrOptions = undefined;
    mocks.actionHooksMounted = 0;
    mocks.reportTasks = undefined;
  });
  afterEach(cleanup);

  it.each([
    {
      name: "ready and actionable",
      report: makeReport(),
      actions: ["Create PR", "Resolve", "Dismiss", "Reviewers"],
    },
    {
      name: "backed by a pull request",
      report: makeReport({
        implementation_pr_url: "https://github.com/PostHog/posthog/pull/1",
      }),
      actions: ["Resolve", "Dismiss", "Reviewers"],
    },
    {
      name: "in progress",
      report: makeReport({ status: "in_progress", actionability: null }),
      actions: ["Dismiss", "Reviewers"],
    },
    {
      name: "suppressed",
      report: makeReport({ status: "suppressed" }),
      actions: ["Restore"],
    },
  ])(
    "offers the right actions when a report is $name",
    ({ report, actions }) => {
      openMenu(report);
      expect(menuItemText()).toEqual([...actions, ...LINK_ITEMS]);
    },
  );

  it.each([
    makeReport({ status: "resolved" }),
    makeReport({
      status: "suppressed",
      refund: { id: "refund-1", reason: "other" },
    }),
  ])("keeps the native context menu for terminal report %#", (report) => {
    openMenu(report);
    expect(menuItemText()).toEqual([]);
    expect(mocks.actionHooksMounted).toBe(0);
  });

  it("applies resolve and dismiss reasons directly", async () => {
    const user = userEvent.setup();
    openMenu(makeReport());

    await user.hover(screen.getByText("Resolve"));
    fireEvent.click(await screen.findByText("PR was merged"));
    expect(mocks.resolveWithReason).toHaveBeenCalledWith("pr_merged");

    fireEvent.contextMenu(screen.getByText("Report one"));
    await user.hover(screen.getByText("Dismiss"));
    fireEvent.click(
      await screen.findByText("Won't fix - intentional behavior"),
    );
    expect(mocks.dismissWithReason).toHaveBeenCalledWith("wontfix_intentional");
  });

  it("opens the reviewer picker on hover", async () => {
    const user = userEvent.setup();
    openMenu(makeReport());

    await user.hover(screen.getByText("Reviewers"));

    expect(await screen.findByText("Reviewer picker")).toBeVisible();
  });

  it("starts PR work from an eligible report", async () => {
    const user = userEvent.setup();
    openMenu(makeReport());

    await user.click(screen.getByText("Create PR"));

    expect(mocks.createPr).toHaveBeenCalledOnce();
    expect(mocks.trackAction).toHaveBeenCalledWith("create_pr", {
      has_feedback: false,
    });
    expect(mocks.trackerSurface).toBe("context_menu");
    expect(mocks.createPrOptions?.surface).toBe("context_menu");
  });

  it("hides Create PR while linked implementation work is active", () => {
    mocks.reportTasks = [
      {
        purpose: "implementation",
        task: { latest_run: { status: "in_progress" } },
      },
    ];

    openMenu(makeReport());

    expect(screen.queryByText("Create PR")).toBeNull();
  });

  it("opens a preselected dialog for other reasons and open pull requests", async () => {
    openMenu(
      makeReport({
        implementation_pr_url: "https://github.com/PostHog/posthog/pull/1",
      }),
    );

    fireEvent.click(screen.getByText("Resolve"));
    fireEvent.click(await screen.findByText("PR was merged"));
    expect(mocks.openResolveDialog).toHaveBeenCalledWith("pr_merged");
    expect(mocks.resolveWithReason).not.toHaveBeenCalled();

    fireEvent.contextMenu(screen.getByText("Report one"));
    fireEvent.click(screen.getByText("Dismiss"));
    fireEvent.click(await screen.findByText("Something else…"));
    expect(mocks.openDismissDialog).toHaveBeenCalledWith("other");
    expect(mocks.dismissWithReason).not.toHaveBeenCalled();

    fireEvent.contextMenu(screen.getByText("Report one"));
    fireEvent.click(screen.getByText("Dismiss"));
    fireEvent.click(await screen.findByText("Already fixed"));
    expect(mocks.openDismissDialog).toHaveBeenCalledWith("already_fixed");
  });

  it("wires restore and copy link actions", async () => {
    const user = userEvent.setup();
    const report = makeReport({ status: "suppressed" });
    openMenu(report);

    await user.click(screen.getByText("Restore"));
    // Analytics fire on click, not via a per-call onSuccess: restore removes
    // the row and unmounts this menu, so a mutation callback could be skipped.
    expect(mocks.trackAction).toHaveBeenCalledWith("restore");
    expect(mocks.restore).toHaveBeenCalledWith(report.id);

    fireEvent.contextMenu(screen.getByText("Report one"));
    await user.click(screen.getByText("Copy link"));
    expect(mocks.copyLink).toHaveBeenCalledWith(report);
    expect(mocks.trackAction).toHaveBeenCalledWith("copy_link");
  });
});
