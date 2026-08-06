import type { SignalReport } from "@posthog/shared/types";
import type { Meta, StoryObj } from "@storybook/react-vite";
import { ReportCard } from "./ReportCard";

const report = (overrides: Partial<SignalReport> = {}): SignalReport => ({
  id: "report-1",
  title:
    "feat(billing-portal): surface usage caps before the invoice surprises anyone",
  summary:
    "Three teammates hit the same confusion this week: usage crossed the cap mid-cycle and the first signal anyone saw was the invoice.",
  status: "ready",
  total_weight: 6,
  signal_count: 5,
  created_at: "2026-08-02T09:00:00Z",
  updated_at: "2026-08-06T10:00:00Z",
  artefact_count: 2,
  priority: "P2",
  actionability: "immediately_actionable",
  source_products: ["error_tracking", "session_replay"],
  ...overrides,
});

const meta: Meta<typeof ReportCard> = {
  title: "Inbox/ReportCard",
  component: ReportCard,
  args: {
    report: report(),
    onDismiss: () => {},
  },
};
export default meta;
type Story = StoryObj<typeof ReportCard>;

export const WrappingTitle: Story = {
  decorators: [
    (StoryFn) => (
      <div style={{ maxWidth: 720, margin: "2rem auto", padding: "0 1rem" }}>
        <StoryFn />
      </div>
    ),
  ],
};

/** Below ~32rem of card width the actions rail stacks under the content. */
export const Narrow: Story = {
  decorators: [
    (StoryFn) => (
      <div style={{ maxWidth: 360, margin: "2rem auto", padding: "0 1rem" }}>
        <StoryFn />
      </div>
    ),
  ],
};

export const Archived: Story = {
  args: {
    variant: "archived",
    report: report({
      status: "suppressed",
      dismissal_reason: "already_fixed",
      dismissal_note: "Shipped in the previous billing release.",
    }),
    onRestore: () => {},
  },
  decorators: [
    (StoryFn) => (
      <div style={{ maxWidth: 720, margin: "2rem auto", padding: "0 1rem" }}>
        <StoryFn />
      </div>
    ),
  ],
};
