import type { Meta, StoryObj } from "@storybook/react";
import type { ReactNode } from "react";
import { ReportCostsSectionView } from "./ReportCostsSection";

const asideWidth = (Story: () => ReactNode) => (
  <div style={{ width: 320 }}>
    <Story />
  </div>
);

const meta: Meta<typeof ReportCostsSectionView> = {
  title: "Inbox/ReportCostsSection",
  component: ReportCostsSectionView,
  args: {
    usage: {
      token_cost_usd: 42.53,
      compute_cost_usd: 7.44,
      total_cost_usd: 49.97,
    },
  },
  decorators: [asideWidth],
};
export default meta;

type Story = StoryObj<typeof ReportCostsSectionView>;

/** The breakdown a click on the header reveals. */
export const Expanded: Story = {
  args: { defaultCollapsed: false },
};

/** Resting state: the visible flag puts the total on the collapsed header. */
export const CollapsedWithTotal: Story = {
  args: { showHeaderTotal: true },
};

/** Sub-cent spend collapses to <$0.01 so a non-zero cost never reads as free. */
export const SubCent: Story = {
  args: {
    usage: {
      token_cost_usd: 0.004,
      compute_cost_usd: 0,
      total_cost_usd: 0.004,
    },
    defaultCollapsed: false,
  },
};
