import {
  ArrowSquareOutIcon,
  CheckCircleIcon,
  EyeSlashIcon,
  GitPullRequestIcon,
} from "@phosphor-icons/react";
import { Button } from "@posthog/quill";
import { inboxStoryReport } from "@posthog/ui/features/inbox/components/inboxStoryFixtures";
import { ReportTriageFocusView } from "@posthog/ui/features/inbox/components/ReportTriageFocusView";
import type { Meta, StoryObj } from "@storybook/react-vite";
import type { ReactNode } from "react";

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
