import { FileTextIcon } from "@phosphor-icons/react";
import { Button } from "@posthog/quill";
import { useRailSurface } from "@posthog/ui/features/canvas/hooks/useRailSurface";
import { InboxDetailFrameView } from "@posthog/ui/features/inbox/components/InboxDetailFrameView";
import { InboxPanePresentation } from "@posthog/ui/features/inbox/components/InboxPanePresentation";
import { InboxPaneRow } from "@posthog/ui/features/inbox/components/InboxPaneRow";
import {
  inboxStoryImplementations,
  inboxStoryReport,
} from "@posthog/ui/features/inbox/components/inboxStoryFixtures";
import {
  ReportTriageFocusView,
  type ReportTriageFocusViewProps,
} from "@posthog/ui/features/inbox/components/ReportTriageFocusView";
import { isInboxTriagePath } from "@posthog/ui/features/inbox/triageRoute";
import type { Meta, StoryObj } from "@storybook/react-vite";
import { useNavigate, useRouterState } from "@tanstack/react-router";
import { type ReactNode, useEffect, useState } from "react";
import { expect, waitFor, within } from "storybook/test";
import { InboxStoryData } from "./InboxStoryData";
import { ReportVerdictBanner } from "./ReportVerdictBanner";

const report = inboxStoryReport();
const previousReport = inboxStoryReport({
  id: "previous-report",
  title: "fix(flags): avoid duplicate evaluations after a reconnect",
  priority: "P2",
});
const nextReport = inboxStoryReport({
  id: "next-report",
  title: "feat(insights): preserve breakdown order in saved results",
  priority: "P2",
});

const viewportAt = (width: number) => (Story: () => ReactNode) => (
  <div className="h-[760px] w-full bg-gray-1" style={{ maxWidth: width }}>
    <Story />
  </div>
);

function TriagePreview(props: ReportTriageFocusViewProps): React.JSX.Element {
  const reports = [props.report, nextReport];
  const [index, setIndex] = useState(0);
  const [expanded, setExpanded] = useState(props.expanded);
  const current = reports[index];
  return (
    <InboxStoryData key={current.id} report={current}>
      <ReportTriageFocusView
        {...props}
        report={current}
        position={index + 1}
        total={reports.length}
        previousReport={reports[index - 1] ?? null}
        nextReport={reports[index + 1] ?? null}
        expanded={expanded}
        actions={
          <ReportVerdictBanner
            key={current.id}
            report={current}
            variant="triage-actions"
            surface="triage"
          />
        }
        onPrevious={() => {
          setIndex(Math.max(0, index - 1));
          setExpanded(false);
        }}
        onNext={() => {
          setIndex(Math.min(reports.length - 1, index + 1));
          setExpanded(false);
        }}
        onToggleSummary={() => setExpanded(!expanded)}
      />
    </InboxStoryData>
  );
}

const meta: Meta<typeof ReportTriageFocusView> = {
  title: "Inbox/Reports/Triage mode",
  component: ReportTriageFocusView,
  tags: ["inbox"],
  parameters: { layout: "fullscreen" },
  decorators: [viewportAt(1100)],
  render: (args) => <TriagePreview {...args} />,
  args: {
    report,
    position: 2,
    total: 8,
    scopeLabel: "For you",
    hasActiveFilters: false,
    previousReport,
    nextReport,
    expanded: false,
    prShortcut: "create",
    canRemoveSelfFromReviewers: true,
    actions: (
      <ReportVerdictBanner
        report={report}
        variant="triage-actions"
        surface="triage"
      />
    ),
    reviewers: (
      <span className="rounded bg-(--gray-3) px-1.5 py-0.5 text-[12px] text-gray-11">
        2 reviewers
      </span>
    ),
    onExit: () => {},
    onPrevious: () => {},
    onNext: () => {},
    onOpenReport: () => {},
    onToggleSummary: () => {},
  },
};

export default meta;
type Story = StoryObj<typeof ReportTriageFocusView>;

export const NeedsAPr: Story = {};

export const FailedTask: Story = {
  args: { report: inboxStoryImplementations[1].report },
  play: async ({ canvas }): Promise<void> => {
    await expect(
      await canvas.findByText(/PR task failed. Open the report to continue/),
    ).toBeVisible();
  },
};

export const WaitingOnYou: Story = {
  args: { report: inboxStoryImplementations[2].report, prShortcut: null },
};

export const NoPrCreated: Story = {
  args: { report: inboxStoryImplementations[4].report },
};

export const ReadAndNavigate: Story = {
  play: async ({ canvas, userEvent }): Promise<void> => {
    await userEvent.click(
      await canvas.findByRole("button", { name: "Read summary" }),
    );
    await expect(
      canvas.getByRole("button", { name: "Hide summary" }),
    ).toBeVisible();
    await userEvent.click(
      canvas.getByRole("button", { name: /preserve breakdown order/ }),
    );
    await expect(
      canvas.getByRole("heading", { name: /preserve breakdown order/ }),
    ).toBeVisible();
  },
};

export const CreatePrOptions: Story = {
  play: async ({ canvas, canvasElement, userEvent }): Promise<void> => {
    await userEvent.click(
      await canvas.findByRole("button", { name: "Create PR", exact: true }),
    );
    const body = within(canvasElement.ownerDocument.body);
    await expect(await body.findByRole("textbox")).toBeVisible();
  },
};

export const ExpandedSummary: Story = {
  args: { expanded: true },
};

export const NotAReviewer: Story = {
  args: { canRemoveSelfFromReviewers: false },
};

export const LongTitle: Story = {
  args: {
    report: inboxStoryReport({
      title:
        "fix(cohorts): prevent overlapping recurring calculations from delaying every queued membership update in large projects",
    }),
  },
};

export const CompactViewport: Story = {
  decorators: [viewportAt(720)],
};

function SidebarRestorationPreview(
  props: ReportTriageFocusViewProps,
): React.JSX.Element {
  const navigate = useNavigate();
  const pathname = useRouterState({
    select: (state) => state.location.pathname,
  });
  const { hasSidebar } = useRailSurface();
  useEffect(() => {
    void navigate({ to: "/inbox" });
  }, [navigate]);
  const enterTriage = () => void navigate({ to: "/inbox/triage" });
  return (
    <div className="flex h-full min-w-0">
      {hasSidebar && (
        <aside
          aria-label="Self-driving sidebar"
          className="w-[272px] shrink-0 border-border border-r bg-chrome"
        >
          <InboxPanePresentation
            reports={[previousReport, report, nextReport]}
            query=""
            onQueryChange={() => {}}
            isLoading={false}
            isFetchingNextPage={false}
            hasNextPage={false}
            hasActiveFilters={false}
            oldestFirst={false}
            filterControl={
              <Button size="sm" variant="outline" onClick={enterTriage}>
                Triage mode
              </Button>
            }
            renderReport={(item) => (
              <InboxPaneRow
                key={item.id}
                report={item}
                isSelected={false}
                optionValue={item.id}
              />
            )}
            onClearFilters={() => {}}
            onLoadMore={() => {}}
          />
        </aside>
      )}
      <main className="min-w-0 flex-1 overflow-auto">
        {isInboxTriagePath(pathname) ? (
          <InboxStoryData report={props.report}>
            <ReportTriageFocusView
              {...props}
              onExit={() => void navigate({ to: "/inbox" })}
              onOpenReport={() =>
                void navigate({
                  to: "/reports/$reportId",
                  params: { reportId: report.id },
                  search: { from: "/inbox/triage" },
                })
              }
            />
          </InboxStoryData>
        ) : pathname.startsWith("/reports/") ? (
          <InboxDetailFrameView
            report={report}
            fallbackTitle="Report"
            primaryAction={
              <Button size="sm" variant="outline" onClick={enterTriage}>
                Triage mode
              </Button>
            }
            summarySection={{ Icon: FileTextIcon, title: "Summary" }}
            evidenceSection={null}
            evidenceCount={0}
            evidenceContent={null}
          />
        ) : (
          <div className="flex h-full items-center justify-center">
            <Button variant="outline" onClick={enterTriage}>
              Start triage
            </Button>
          </div>
        )}
      </main>
    </div>
  );
}

export const SidebarRestoration: Story = {
  render: (args) => <SidebarRestorationPreview {...args} />,
  play: async ({ canvas, userEvent }): Promise<void> => {
    await userEvent.click(
      await canvas.findByRole("button", { name: "Start triage" }),
    );
    await waitFor(() =>
      expect(
        canvas.queryByRole("complementary", { name: "Self-driving sidebar" }),
      ).not.toBeInTheDocument(),
    );
    await userEvent.click(
      await canvas.findByRole("button", { name: "Exit triage" }),
    );
    await expect(
      await canvas.findByRole("complementary", {
        name: "Self-driving sidebar",
      }),
    ).toBeVisible();
    await userEvent.click(canvas.getByRole("button", { name: "Start triage" }));
    await userEvent.click(
      await canvas.findByRole("button", { name: "Open report" }),
    );
    await expect(
      await canvas.findByRole("complementary", {
        name: "Self-driving sidebar",
      }),
    ).toBeVisible();
  },
};
