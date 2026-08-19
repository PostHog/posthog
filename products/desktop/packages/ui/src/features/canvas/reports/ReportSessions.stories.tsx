import type { SignalReport } from "@posthog/shared/types";
import type { Meta, StoryObj } from "@storybook/react-vite";
import { ReportSessionsView } from "./ReportSessionsList";
import { partitionReportSessions } from "./reportSessions";

const report = (overrides: Partial<SignalReport>): SignalReport => ({
  id: "report",
  title: "Report",
  summary: "A concise summary of what changed and why it matters.",
  status: "ready",
  total_weight: 1,
  signal_count: 1,
  created_at: "2026-08-01T00:00:00Z",
  updated_at: "2026-08-01T00:00:00Z",
  artefact_count: 0,
  ...overrides,
});

const populatedSections = partitionReportSessions([
  report({
    id: "report-retention",
    title: "Retention improved after onboarding changes",
    summary:
      "Users who completed the revised onboarding flow returned more often in the following weeks.",
    priority: "P1",
    is_suggested_reviewer: true,
  }),
  report({
    id: "report-errors",
    title: "Checkout errors increased",
    summary:
      "Payment failures rose after the latest checkout release and are concentrated in one browser family.",
    priority: "P0",
  }),
  report({
    id: "report-running",
    title: "Investigate slower dashboard loads",
    summary: "The report is collecting traces from the busiest dashboards.",
    status: "in_progress",
  }),
  report({
    id: "report-pr",
    title: "Reduce duplicate identify calls",
    summary:
      "A proposed change deduplicates repeated identify calls during app startup.",
    implementation_pr_url: "https://github.com/PostHog/posthog/pull/1",
  }),
  report({
    id: "report-archived",
    title: "Legacy SDK traffic",
    summary: "This report was archived after the remaining clients upgraded.",
    status: "suppressed",
  }),
]);

const meta: Meta<typeof ReportSessionsView> = {
  title: "Canvas/Report sessions",
  component: ReportSessionsView,
  args: {
    channelId: "report-space",
    loading: false,
    error: false,
  },
  parameters: {
    layout: "fullscreen",
    testOptions: { viewport: { width: 1280, height: 900 } },
  },
};

export default meta;
type Story = StoryObj<typeof ReportSessionsView>;

export const Populated: Story = {
  args: { sections: populatedSections },
};

export const Empty: Story = {
  args: { sections: partitionReportSessions([]) },
};
