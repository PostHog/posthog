import type {
  AnySignalReportArtefact,
  Signal,
  SignalReport,
  Task,
} from "@posthog/shared/types";
import type { ReportTaskData } from "@posthog/ui/features/inbox/hooks/useReportTasks";
import type { Meta, StoryObj } from "@storybook/react-vite";
import { ReportWorkspaceView } from "./ReportCanvas";

const baseReport: SignalReport = {
  id: "report-checkout-errors",
  title: "Checkout errors increased after the latest release",
  summary:
    "Payment failures increased after the latest checkout release. The change is concentrated in Safari sessions using saved payment methods.",
  status: "ready",
  total_weight: 8,
  signal_count: 4,
  created_at: "2026-08-08T09:00:00Z",
  updated_at: "2026-08-10T11:30:00Z",
  artefact_count: 5,
  priority: "P1",
  actionability: "immediately_actionable",
  already_addressed: false,
  source_products: ["error_tracking", "session_replay"],
};

const signals: Signal[] = [
  {
    signal_id: "signal-errors",
    content:
      "Payment confirmation failures cluster around the saved-card checkout path in Safari.",
    source_product: "error_tracking",
    source_type: "issue",
    source_id: "issue-example",
    weight: 4,
    timestamp: "2026-08-10T10:00:00Z",
    extra: {},
  },
  {
    signal_id: "signal-replays",
    content:
      "Affected sessions repeatedly submit the payment form after the confirmation step stalls.",
    source_product: "session_replay",
    source_type: "cluster",
    source_id: "cluster-example",
    weight: 3,
    timestamp: "2026-08-10T09:00:00Z",
    extra: {},
  },
];

const artefacts: AnySignalReportArtefact[] = [
  {
    id: "actionability",
    type: "actionability_judgment",
    created_at: "2026-08-10T11:00:00Z",
    content: {
      actionability: "immediately_actionable",
      already_addressed: false,
      explanation:
        "The failure begins in a recently changed checkout path and has a focused reproduction case.",
    },
  },
];

function task(id: string, title: string, prUrl?: string): Task {
  return {
    id,
    task_number: null,
    slug: id,
    title,
    description: title,
    created_at: "2026-08-10T10:00:00Z",
    updated_at: "2026-08-10T11:00:00Z",
    origin_product: "signal_report",
    latest_run: {
      id: `${id}-run`,
      task: id,
      team: 1,
      branch: null,
      status: "completed",
      log_url: "",
      error_message: null,
      output: prUrl ? { pr_url: prUrl } : null,
      state: {},
      created_at: "2026-08-10T10:00:00Z",
      updated_at: "2026-08-10T11:00:00Z",
      completed_at: "2026-08-10T11:00:00Z",
    },
  };
}

const reportTasks: ReportTaskData[] = [
  {
    task: task("research", "Trace the saved-card checkout failure"),
    purpose: "research",
    purposeLabel: "Research",
    startedAt: "2026-08-10T10:00:00Z",
  },
];

function ConversationFixture() {
  return (
    <div className="flex h-full flex-col">
      <div className="flex h-11 items-center gap-2 border-b px-4">
        <span className="font-semibold">Conversation</span>
      </div>
      <div className="flex flex-1 flex-col gap-4 overflow-y-auto p-5">
        <div className="max-w-[75%] self-end rounded-lg bg-primary px-4 py-3 text-primary-foreground">
          Why did this start after the release?
        </div>
        <div className="max-w-[80%] rounded-lg border bg-surface-secondary px-4 py-3">
          The failures begin after the saved payment method is restored in
          Safari. I found one recent change in that path and two replay sessions
          with the same stalled confirmation step.
        </div>
      </div>
      <div className="border-t p-3">
        <div className="rounded-lg border bg-surface-primary px-4 py-3 text-muted-foreground">
          Ask about this report...
        </div>
      </div>
    </div>
  );
}

const meta: Meta<typeof ReportWorkspaceView> = {
  title: "Canvas/Report workspace",
  component: ReportWorkspaceView,
  args: {
    report: baseReport,
    signals,
    artefacts,
    reportTasks,
    conversation: <ConversationFixture />,
  },
  parameters: {
    layout: "fullscreen",
    testOptions: { viewport: { width: 1440, height: 900 } },
  },
};

export default meta;
type Story = StoryObj<typeof ReportWorkspaceView>;

export const Actionable: Story = {};

export const ExistingPullRequest: Story = {
  args: {
    report: {
      ...baseReport,
      title: "Duplicate identify calls during app startup",
      summary:
        "Repeated identify calls during startup add unnecessary network traffic. The self-driving pipeline prepared a deduplication change.",
      implementation_pr_url: "https://github.com/PostHog/posthog/pull/1",
    },
    reportTasks: [
      ...reportTasks,
      {
        task: task(
          "implementation",
          "Deduplicate identify during startup",
          "https://github.com/PostHog/posthog/pull/1",
        ),
        purpose: "implementation",
        purposeLabel: "Implementation",
        startedAt: "2026-08-10T11:00:00Z",
      },
    ],
  },
};

export const NeedsMoreEvidence: Story = {
  args: {
    report: {
      ...baseReport,
      title: "Dashboard loads may be slowing down",
      summary:
        "A small group of traces shows slower dashboard loads, but the affected segment and cause are not clear yet.",
      status: "in_progress",
      actionability: null,
      priority: null,
      signal_count: 1,
    },
    signals: signals.slice(0, 1),
    artefacts: [],
  },
};
