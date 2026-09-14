import {
  ChatCircleIcon,
  CheckCircleIcon,
  ClockCounterClockwiseIcon,
  EyeSlashIcon,
  FileTextIcon,
  GitPullRequestIcon,
  MagnifyingGlassIcon,
  PlusIcon,
  ReceiptIcon,
  TerminalIcon,
  UsersThreeIcon,
  XIcon,
} from "@phosphor-icons/react";
import { deriveReportVerdict } from "@posthog/core/inbox/reportVerdict";
import { Button } from "@posthog/quill";
import { DetailSection } from "@posthog/ui/features/inbox/components/DetailSection";
import { InboxDetailFrameView } from "@posthog/ui/features/inbox/components/InboxDetailFrameView";
import {
  inboxStoryReport,
  inboxStorySignal,
} from "@posthog/ui/features/inbox/components/inboxStoryFixtures";
import { ReportVerdictCallout } from "@posthog/ui/features/inbox/components/ReportVerdictCallout";
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
  <div className="min-h-[760px] w-full bg-gray-1" style={{ maxWidth: width }}>
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
    showMetadata: true,
    summarySection: { Icon: FileTextIcon, title: "Summary" },
    evidenceSection: { Icon: MagnifyingGlassIcon, title: "Evidence" },
    evidenceCount: signals.length,
    evidenceContent: <SignalsList signals={signals} />,
    belowSummary: (
      <div className="flex select-none flex-col gap-3 rounded-lg border border-(--amber-6) bg-(--amber-2) p-4">
        <div className="flex flex-col gap-1">
          <span className="font-semibold text-[15px] text-gray-12">
            Needs your decision
          </span>
          <span className="text-[14px] text-gray-11">
            The agent can fix this with code and open a pull request. The report
            reopens if the problem comes back.
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
    footer: (
      <p className="m-0 text-[13px] text-gray-11">Was this report useful?</p>
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

export const LikelyAlreadyFixed: Story = {
  args: {
    report: inboxStoryReport({ already_addressed: true }),
    belowSummary: (
      <ReportVerdictCallout
        verdict={deriveReportVerdict(
          inboxStoryReport({ already_addressed: true }),
          { hasExistingPr: false },
        )}
      >
        <div className="flex flex-wrap items-center gap-2.5">
          <Button variant="outline">
            <ChatCircleIcon />
            Ask about it
          </Button>
          <Button variant="outline">
            <EyeSlashIcon />
            Dismiss…
          </Button>
        </div>
      </ReportVerdictCallout>
    ),
  },
};

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
  decorators: [pageAt(520)],
};

export const WithPullRequest: Story = {
  args: {
    report: inboxStoryReport({
      implementation_pr_url: "https://github.com/example/project/pull/42",
    }),
    primaryAction: (
      <>
        <Button variant="outline" size="sm">
          Open in GitHub
        </Button>
        <Button variant="outline" size="sm">
          <ChatCircleIcon />
          Chat
        </Button>
        <Button variant="outline" size="sm">
          <EyeSlashIcon />
          Dismiss
        </Button>
        <Button variant="outline" size="sm">
          <ReceiptIcon />
          Refund
        </Button>
      </>
    ),
    summarySection: { Icon: FileTextIcon, title: "Summary" },
    secondaryTab: {
      label: "Changed code",
      content: <p>Changed files appear here.</p>,
    },
    belowSummary: null,
  },
};
