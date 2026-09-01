import { Button } from "@posthog/quill";
import type { SignalReport } from "@posthog/shared/types";
import { InboxReportContextMenu } from "@posthog/ui/features/inbox/components/InboxReportContextMenu";
import { InboxReportFilters } from "@posthog/ui/features/inbox/components/InboxReportFilters";
import { InboxReportRowView } from "@posthog/ui/features/inbox/components/InboxReportRowView";
import { InboxReportSection } from "@posthog/ui/features/inbox/components/InboxReportSection";
import { inboxStoryReport } from "@posthog/ui/features/inbox/components/inboxStoryFixtures";
import { ReportsInboxViewPresentation } from "@posthog/ui/features/inbox/components/ReportsInboxViewPresentation";
import type { Meta, StoryObj } from "@storybook/react-vite";

const reviewAndMerge = [
  inboxStoryReport({
    id: "review-1",
    title: "fix(cohorts): keep recurring calculations within their budget",
    implementation_pr_url: "https://github.com/PostHog/posthog/pull/12345",
  }),
  inboxStoryReport({
    id: "review-2",
    title: "feat(replay): expose buffer health in the player controls",
    priority: "P2",
    signal_count: 3,
    implementation_pr_url: "https://github.com/PostHog/posthog/pull/12346",
  }),
];

const needsPr = Array.from({ length: 8 }, (_, index) =>
  inboxStoryReport({
    id: `needs-pr-${index + 1}`,
    title: `${index % 2 === 0 ? "fix(flags)" : "feat(insights)"}: ${
      index % 2 === 0
        ? "avoid duplicate evaluations after a reconnect"
        : "preserve breakdown order in saved results"
    }`,
    priority: index < 2 ? "P1" : "P2",
    signal_count: 9 - index,
  }),
);

const resolved = [
  inboxStoryReport({
    id: "resolved-1",
    status: "resolved",
    title: "fix(webhooks): retry delivery after a transient timeout",
  }),
  inboxStoryReport({
    id: "resolved-2",
    status: "suppressed",
    title: "chore(settings): clarify an unused configuration path",
    dismissal_reason: "not_enough_evidence",
  }),
];

function reportRow(report: SignalReport): React.JSX.Element {
  return (
    <InboxReportContextMenu key={report.id} report={report}>
      <InboxReportRowView
        report={report}
        reviewers={
          <span
            className="h-5 w-5 rounded-full border-(--color-panel-solid) border-2 bg-(--accent-5)"
            role="img"
            aria-label="One suggested reviewer"
          />
        }
        onOpen={() => {}}
        onOpenPr={() => {}}
      />
    </InboxReportContextMenu>
  );
}

const meta: Meta<typeof ReportsInboxViewPresentation> = {
  title: "Inbox/Reports/List view",
  component: ReportsInboxViewPresentation,
  parameters: { layout: "fullscreen" },
  decorators: [
    (Story) => (
      <div className="h-[760px] min-w-[720px]">
        <Story />
      </div>
    ),
  ],
  args: {
    reviewAndMerge,
    reviewAndMergeCount: reviewAndMerge.length,
    showReviewAndMerge: true,
    needsPr,
    needsPrCount: needsPr.length,
    showNeedsDecision: true,
    isLoading: false,
    isFetchingNextPage: false,
    isEmpty: false,
    hasActiveFilters: false,
    triageEnabled: true,
    filterControl: <InboxReportFilters />,
    scopeControl: (
      <Button type="button" variant="outline" size="sm">
        For you
      </Button>
    ),
    resolvedSection: (
      <InboxReportSection
        title="Resolved"
        reports={resolved}
        count={resolved.length}
        defaultOpen={false}
        renderReport={reportRow}
      />
    ),
    renderReport: reportRow,
    onConfigureAgents: () => {},
    onEnterTriage: () => {},
    onClearFilters: () => {},
  },
};

export default meta;
type Story = StoryObj<typeof ReportsInboxViewPresentation>;

export const MixedQueue: Story = {};

export const EmptyInbox: Story = {
  args: {
    reviewAndMerge: [],
    reviewAndMergeCount: 0,
    needsPr: [],
    needsPrCount: 0,
    isEmpty: true,
    resolvedSection: undefined,
  },
};

export const FilteredEmpty: Story = {
  args: {
    reviewAndMerge: [],
    reviewAndMergeCount: 0,
    needsPr: [],
    needsPrCount: 0,
    isEmpty: true,
    hasActiveFilters: true,
    resolvedSection: undefined,
  },
};

export const Loading: Story = {
  args: {
    reviewAndMerge: [],
    reviewAndMergeCount: 0,
    needsPr: [],
    needsPrCount: 0,
    isLoading: true,
    isEmpty: false,
    resolvedSection: undefined,
  },
};
