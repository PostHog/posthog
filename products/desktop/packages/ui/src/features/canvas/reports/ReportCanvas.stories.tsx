import type {
  AnySignalReportArtefact,
  Signal,
  SignalReport,
} from "@posthog/shared/types";
import type { Meta, StoryObj } from "@storybook/react-vite";
import { fn } from "storybook/test";
import { ReportStoryCanvas } from "./ReportCanvas";

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

const meta: Meta<typeof ReportStoryCanvas> = {
  title: "Canvas/Report story canvas",
  component: ReportStoryCanvas,
  args: {
    report: baseReport,
    signals,
    artefacts,
    reportTasks: [],
    onPrompt: fn(),
  },
  parameters: {
    layout: "fullscreen",
    testOptions: { viewport: { width: 1000, height: 950 } },
  },
};

export default meta;
type Story = StoryObj<typeof ReportStoryCanvas>;

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
