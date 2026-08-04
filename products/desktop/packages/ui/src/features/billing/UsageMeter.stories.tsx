import { UsageMeter } from "@posthog/ui/features/billing/UsageMeter";
import type { Meta, StoryObj } from "@storybook/react-vite";

const meta: Meta<typeof UsageMeter> = {
  title: "Billing/UsageMeter",
  component: UsageMeter,
  decorators: [
    (Story) => (
      <div style={{ maxWidth: 560 }}>
        <Story />
      </div>
    ),
  ],
};

export default meta;
type Story = StoryObj<typeof UsageMeter>;

// A subscribed org on default settings: the $70 limit renders as two
// segments — the $20 included allowance (green) and the $50 default spend
// limit (accent) — with a dot legend naming each amount. Usage still inside
// the included allowance only fills the green segment.
export const SubscribedWithBreakdown: Story = {
  args: {
    label: "Usage this period",
    percent: 18,
    valueLabel: "$12.40 of $70",
    detail: "Resets Jul 31 at 2:00 PM PDT",
    breakdown: { includedUsd: 20, spendLimitUsd: 50, usedUsd: 12.4 },
  },
};

// Past the allowance: the green segment is full and billable usage fills the
// accent segment.
export const SubscribedPastIncluded: Story = {
  args: {
    label: "Usage this period",
    percent: 66,
    valueLabel: "$46.20 of $70",
    detail: "Resets Jul 31 at 2:00 PM PDT",
    breakdown: { includedUsd: 20, spendLimitUsd: 50, usedUsd: 46.2 },
  },
};

// A subscribed org that set its spend limit to $0: only the included segment
// (and its legend entry) renders.
export const ZeroSpendLimit: Story = {
  args: {
    label: "Usage this period",
    percent: 65,
    valueLabel: "$13 of $20",
    detail: "Resets Jul 31 at 2:00 PM PDT",
    breakdown: { includedUsd: 20, spendLimitUsd: 0, usedUsd: 13 },
  },
};

// Free tier has no breakdown — its limit IS the allowance, so the plain
// single-track bar renders.
export const FreeTier: Story = {
  args: {
    label: "Monthly free usage",
    percent: 62,
    valueLabel: "$12.40 of $20 included",
    detail: "Resets Jul 31 at 2:00 PM PDT",
  },
};

export const Exceeded: Story = {
  args: {
    label: "Usage this period",
    percent: 100,
    valueLabel: "$70 of $70",
    detail: "Limit exceeded. Resets Jul 31 at 2:00 PM PDT",
    breakdown: { includedUsd: 20, spendLimitUsd: 50, usedUsd: 70 },
    color: "red",
  },
};
