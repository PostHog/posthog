import type { Meta, StoryObj } from "@storybook/react-vite";
import { PlatformStatusBannerRow } from "./PlatformStatusBannerRow";

const meta: Meta<typeof PlatformStatusBannerRow> = {
  title: "Platform status/PlatformStatusBanner",
  component: PlatformStatusBannerRow,
  tags: ["platform-status"],
  args: {
    onOpenStatusPage: () => {},
  },
  decorators: [
    (Story) => (
      <div style={{ maxWidth: 960, margin: "1rem auto" }}>
        <Story />
      </div>
    ),
  ],
};

export default meta;
type Story = StoryObj<typeof PlatformStatusBannerRow>;

export const DegradedPerformance: Story = {
  args: { status: "degraded_performance" },
};

export const PartialOutage: Story = {
  args: { status: "partial_outage" },
};
