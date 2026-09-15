import {
  ArrowSquareOutIcon,
  CheckCircleIcon,
  EyeSlashIcon,
  FileTextIcon,
  GitPullRequestIcon,
} from "@phosphor-icons/react";
import { Button } from "@posthog/quill";
import { useRailSurface } from "@posthog/ui/features/canvas/hooks/useRailSurface";
import { InboxDetailFrameView } from "@posthog/ui/features/inbox/components/InboxDetailFrameView";
import { InboxPanePresentation } from "@posthog/ui/features/inbox/components/InboxPanePresentation";
import { InboxPaneRow } from "@posthog/ui/features/inbox/components/InboxPaneRow";
import { inboxStoryReport } from "@posthog/ui/features/inbox/components/inboxStoryFixtures";
import {
  ReportTriageFocusView,
  type ReportTriageFocusViewProps,
} from "@posthog/ui/features/inbox/components/ReportTriageFocusView";
import { isInboxTriagePath } from "@posthog/ui/features/inbox/triageRoute";
import type { Meta, StoryObj } from "@storybook/react-vite";
import { useNavigate, useRouterState } from "@tanstack/react-router";
import { type ReactNode, useEffect } from "react";

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
  <div className="h-[760px] bg-gray-1" style={{ width }}>
    <Story />
  </div>
);

function createPrActions(): React.JSX.Element {
  return (
    <div className="flex flex-wrap items-center gap-2.5">
      <Button
        type="button"
        variant="outline"
        className="h-9 gap-2 px-4 text-[14px]"
      >
        <CheckCircleIcon />
        Resolve
      </Button>
      <Button
        type="button"
        variant="outline"
        className="h-9 gap-2 px-4 text-[14px]"
      >
        <EyeSlashIcon />
        Dismiss
      </Button>
      <Button
        type="button"
        variant="primary"
        className="h-9 gap-2 px-4 text-[14px]"
      >
        <GitPullRequestIcon />
        Create PR
      </Button>
    </div>
  );
}

function openPrActions(): React.JSX.Element {
  return (
    <div className="flex flex-wrap items-center gap-2.5">
      <Button
        type="button"
        variant="outline"
        className="h-9 gap-2 px-4 text-[14px]"
      >
        <CheckCircleIcon />
        Resolve
      </Button>
      <Button
        type="button"
        variant="outline"
        className="h-9 gap-2 px-4 text-[14px]"
      >
        <EyeSlashIcon />
        Dismiss
      </Button>
      <Button
        type="button"
        variant="primary"
        className="h-9 gap-2 px-4 text-[14px]"
      >
        <ArrowSquareOutIcon />
        View PR on GitHub
      </Button>
    </div>
  );
}

const meta: Meta<typeof ReportTriageFocusView> = {
  title: "Inbox/Reports/Triage mode",
  component: ReportTriageFocusView,
  parameters: { layout: "fullscreen" },
  decorators: [viewportAt(1100)],
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
    actions: createPrActions(),
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

export const ExistingPr: Story = {
  args: {
    report: inboxStoryReport({
      implementation_pr_url: "https://github.com/PostHog/posthog/pull/12345",
    }),
    prShortcut: "open",
    actions: openPrActions(),
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
};
