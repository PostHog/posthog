import {
  ChatCircleIcon,
  CheckCircleIcon,
  ClockCounterClockwiseIcon,
  EyeSlashIcon,
  FileTextIcon,
  MagnifyingGlassIcon,
  PlusIcon,
  ReceiptIcon,
  TerminalIcon,
  UsersThreeIcon,
  XIcon,
} from "@phosphor-icons/react";
import { useHostTRPC } from "@posthog/host-router/react";
import { Button } from "@posthog/quill";
import { DetailSection } from "@posthog/ui/features/inbox/components/DetailSection";
import { InboxDetailFrameView } from "@posthog/ui/features/inbox/components/InboxDetailFrameView";
import {
  inboxStoryImplementations,
  inboxStoryReport,
  inboxStorySignal,
} from "@posthog/ui/features/inbox/components/inboxStoryFixtures";
import { ReportVerdictBanner } from "@posthog/ui/features/inbox/components/ReportVerdictBanner";
import { SignalsList } from "@posthog/ui/features/inbox/components/SignalsList";
import { PrDecisionBlock } from "@posthog/ui/features/pr-review/PrDecisionBlock";
import { PrFilesChangedSection } from "@posthog/ui/features/pr-review/PrFilesChangedSection";
import type { Meta, StoryObj } from "@storybook/react-vite";
import { useQueryClient } from "@tanstack/react-query";
import type { ReactNode } from "react";
import { expect, waitFor } from "storybook/test";
import { ReportFeedbackFooter } from "./detail/ReportFeedbackFooter";
import { InboxStoryData } from "./InboxStoryData";

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
  tags: ["inbox"],
  parameters: { layout: "fullscreen" },
  decorators: [
    pageAt(1360),
    (Story, context) => (
      <InboxStoryData report={context.args.report}>
        <Story />
      </InboxStoryData>
    ),
  ],
  render: (args) => (
    <InboxDetailFrameView
      {...args}
      belowSummary={
        args.belowSummary === undefined ? (
          <ReportVerdictBanner report={args.report} />
        ) : (
          args.belowSummary
        )
      }
      footer={
        <ReportFeedbackFooter key={args.report.id} report={args.report} />
      }
    />
  ),
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
  args: { report: inboxStoryReport({ already_addressed: true }) },
};

export const WaitingForInput: Story = {
  args: { report: inboxStoryImplementations[2].report },
};

export const CreatingPr: Story = {
  args: { report: inboxStoryImplementations[0].report },
};

export const FailedTask: Story = {
  args: { report: inboxStoryImplementations[1].report },
};

export const Feedback: Story = {
  play: async ({ canvas, userEvent }): Promise<void> => {
    await userEvent.click(
      await canvas.findByRole("button", { name: "This report was useful" }),
    );
    await expect(canvas.getByText("Thanks for the feedback")).toBeVisible();
    await userEvent.click(canvas.getByRole("button", { name: "Add a note" }));
    await expect(
      canvas.getByRole("textbox", { name: "Add a note about this report" }),
    ).toBeVisible();
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

const prUrl = "https://github.com/example/project/pull/42";

export const WithPullRequest: Story = {
  decorators: [
    (Story, context) => {
      const trpc = useHostTRPC();
      const queryClient = useQueryClient();
      queryClient.setQueryData(trpc.git.getPrInfoByUrl.queryKey({ prUrl }), {
        number: 42,
        title: "Coalesce pending cohort calculations",
        body: "Keep only the newest queued calculation.",
        author: null,
        state: "open",
        merged: false,
        draft: context.parameters.draft ?? false,
        mergeable: true,
        mergeStateStatus: "clean",
        baseRefName: "main",
        headRefName: "fix-cohort-queue",
        additions: 1,
        deletions: 1,
        changedFiles: 1,
      });
      queryClient.setQueryData(trpc.git.getPrChecks.queryKey({ prUrl }), [
        {
          name: "Unit tests",
          bucket: context.parameters.failing ? "fail" : "pass",
          link: null,
          workflow: "Tests",
          description: null,
        },
      ]);
      queryClient.setQueryData(trpc.git.getPrChangedFiles.queryKey({ prUrl }), [
        {
          path: "src/cohortQueue.ts",
          status: "modified",
          linesAdded: 1,
          linesRemoved: 1,
          patch:
            "diff --git a/src/cohortQueue.ts b/src/cohortQueue.ts\n--- a/src/cohortQueue.ts\n+++ b/src/cohortQueue.ts\n@@ -1,3 +1,3 @@\n export function enqueue(cohortId: string) {\n-  return queue.add(cohortId);\n+  return queue.replacePending(cohortId);\n }\n",
        },
      ]);
      return <Story />;
    },
  ],
  args: {
    report: inboxStoryReport({ implementation_pr_url: prUrl }),
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
    secondaryTab: {
      label: "Changed code",
      content: <PrFilesChangedSection prUrl={prUrl} bare />,
    },
    belowSummary: <PrDecisionBlock prUrl={prUrl} />,
    children: (
      <DetailSection Icon={UsersThreeIcon} title="Reviewers" collapsible>
        <p className="text-[13px] text-gray-11">Example reviewer</p>
      </DetailSection>
    ),
  },
};

export const DraftPullRequest: Story = {
  ...WithPullRequest,
  parameters: { draft: true },
};

export const FailingPullRequest: Story = {
  ...WithPullRequest,
  parameters: { failing: true },
};

export const ChangedCode: Story = {
  ...WithPullRequest,
  play: async ({ canvas, canvasElement, userEvent }): Promise<void> => {
    await userEvent.click(
      await canvas.findByRole("tab", { name: "Changed code" }),
    );
    await expect(await canvas.findByText("1 file changed")).toBeVisible();
    await waitFor(() => {
      const diffText = Array.from(canvasElement.querySelectorAll("*"))
        .map((element) => element.shadowRoot?.textContent ?? "")
        .join(" ");
      expect(diffText).toContain("queue.replacePending");
    });
  },
};

export const NarrowPullRequest: Story = {
  ...WithPullRequest,
  decorators: [...(WithPullRequest.decorators ?? []), pageAt(520)],
};

export const NarrowChangedCode: Story = {
  ...ChangedCode,
  decorators: [...(WithPullRequest.decorators ?? []), pageAt(520)],
};
