import {
  ChatCircleIcon,
  CheckCircleIcon,
  ClockCounterClockwiseIcon,
  EyeSlashIcon,
  FileTextIcon,
  GitPullRequestIcon,
  MagnifyingGlassIcon,
  PlusIcon,
  TerminalIcon,
  UsersThreeIcon,
  XIcon,
} from "@phosphor-icons/react";
import { Button } from "@posthog/quill";
import { DetailSection } from "@posthog/ui/features/inbox/components/DetailSection";
import { InboxDetailFrameView } from "@posthog/ui/features/inbox/components/InboxDetailFrameView";
import {
  inboxStoryReport,
  inboxStorySignal,
} from "@posthog/ui/features/inbox/components/inboxStoryFixtures";
import { SignalsList } from "@posthog/ui/features/inbox/components/SignalsList";
import type { Meta, StoryObj } from "@storybook/react-vite";
import type { ReactNode } from "react";

const report = inboxStoryReport();
const signals = [
  inboxStorySignal(),
  inboxStorySignal({
    signal_id: "story-signal-2",
    content:
      "A second scheduled calculation started before the previous calculation released its lease.",
    timestamp: "2026-08-26T16:15:00Z",
  }),
];

const pageAt = (width: number) => (Story: () => ReactNode) => (
  <div className="min-h-[760px] bg-gray-1" style={{ width }}>
    <Story />
  </div>
);

const meta: Meta<typeof InboxDetailFrameView> = {
  title: "Inbox/Reports/Single report",
  component: InboxDetailFrameView,
  parameters: { layout: "fullscreen" },
  decorators: [pageAt(1360)],
  args: {
    report,
    backTo: "/inbox/reports",
    backLabel: "Back to reports",
    fallbackTitle: "Untitled report",
    primaryAction: (
      <>
        <Button type="button" variant="outline" size="sm">
          <ChatCircleIcon />
          Chat
        </Button>
        <Button type="button" variant="outline" size="sm">
          <CheckCircleIcon />
          Resolve
        </Button>
        <Button type="button" variant="outline" size="sm">
          <EyeSlashIcon />
          Dismiss
        </Button>
      </>
    ),
    showMetadata: false,
    summarySection: { Icon: FileTextIcon, title: "Report summary" },
    evidenceSection: { Icon: MagnifyingGlassIcon, title: "Evidence" },
    evidenceCount: signals.length,
    evidenceContent: <SignalsList signals={signals} />,
    runRepository: "PostHog/posthog",
    belowSummary: (
      <div className="flex flex-wrap items-center justify-between gap-3 rounded-(--radius-2) border border-(--amber-6) bg-(--amber-2) p-4">
        <div className="flex min-w-0 flex-col gap-1">
          <span className="font-semibold text-[14px] text-gray-12">
            Ready for a decision
          </span>
          <span className="text-[13px] text-gray-11">
            Start a pull request or dismiss this report.
          </span>
        </div>
        <div className="flex items-center gap-2">
          <Button type="button" variant="outline">
            <EyeSlashIcon />
            Dismiss…
          </Button>
          <Button type="button" variant="primary">
            <GitPullRequestIcon />
            Create PR
          </Button>
        </div>
      </div>
    ),
    children: (
      <>
        <DetailSection
          Icon={UsersThreeIcon}
          title="Reviewers"
          collapsible
          rightSlot={
            <Button type="button" variant="link-muted" size="xs">
              <PlusIcon />
              Add
            </Button>
          }
        >
          <div className="flex items-start justify-between gap-2">
            <p className="m-0 text-[13px] text-gray-11">
              Example reviewer · recent ownership in cohort calculations
            </p>
            <Button
              type="button"
              variant="link-muted"
              size="icon-xs"
              aria-label="Remove example reviewer"
            >
              <XIcon />
            </Button>
          </div>
        </DetailSection>
        <DetailSection
          Icon={TerminalIcon}
          title="Runs"
          collapsible
          defaultCollapsed
        >
          <p className="text-[13px] text-gray-11">
            Research completed 3 days ago
          </p>
        </DetailSection>
        <DetailSection
          Icon={ClockCounterClockwiseIcon}
          title="Activity"
          collapsible
          defaultCollapsed
        >
          <p className="text-[13px] text-gray-11">
            Priority changed from P2 to P1
          </p>
        </DetailSection>
      </>
    ),
  },
};

export default meta;
type Story = StoryObj<typeof InboxDetailFrameView>;

export const EvidenceFirst: Story = {};

export const WaitingForInput: Story = {
  args: {
    report: inboxStoryReport({
      status: "pending_input",
      actionability: "requires_human_input",
    }),
    belowSummary: (
      <div className="flex select-none flex-col gap-3 rounded-lg border border-(--amber-6) bg-(--amber-2) p-4">
        <div className="flex flex-col gap-1">
          <span className="font-semibold text-[15px] text-gray-12">
            Waiting on you
          </span>
          <span className="text-[14px] text-gray-11">
            Review the recommendation. Start an implementation task to add
            direction and choose a model, or ask for more context.
          </span>
        </div>
        <div className="flex flex-wrap items-center gap-2.5">
          <Button type="button" variant="primary">
            <GitPullRequestIcon />
            Implement
          </Button>
          <Button type="button" variant="outline">
            <ChatCircleIcon />
            Ask about it
          </Button>
          <Button type="button" variant="outline">
            <EyeSlashIcon />
            Dismiss…
          </Button>
        </div>
      </div>
    ),
  },
};

export const NoEvidence: Story = {
  args: {
    report: inboxStoryReport({ signal_count: 0 }),
    evidenceCount: 0,
    evidenceContent: undefined,
  },
};

export const LongTitle: Story = {
  args: {
    report: inboxStoryReport({
      title:
        "fix(cohorts): prevent overlapping recurring calculations from delaying every queued membership update in large projects",
    }),
  },
};

export const Narrow: Story = {
  decorators: [pageAt(720)],
};
