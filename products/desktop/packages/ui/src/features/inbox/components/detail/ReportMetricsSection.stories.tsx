import type { Meta, StoryObj } from "@storybook/react";
import { ReportMetricTileView } from "./ReportMetricsSection";

const meta: Meta<typeof ReportMetricTileView> = {
  title: "Inbox/ReportMetricTile",
  component: ReportMetricTileView,
  decorators: [
    (Story) => (
      <dl className="m-0 grid max-w-[640px] grid-cols-3 gap-2">
        <Story />
      </dl>
    ),
  ],
};
export default meta;

type Story = StoryObj<typeof ReportMetricTileView>;

/** The report's key observation, with the change against the previous bucket. */
export const Lead: Story = {
  args: {
    title: "Affected users",
    value: { value: "87,342", suffix: "users" },
    trend: { label: "12%", direction: "up" },
    caption: "Sessions on the checkout page only.",
    isLead: true,
  },
};

export const Supporting: Story = {
  args: {
    title: "Error rate",
    value: { value: "4.2%", suffix: null },
    trend: { label: "3.1%", direction: "down" },
  },
};

/** The live query failed, so the report keeps the last saved snapshot. */
export const StaleSnapshot: Story = {
  args: {
    title: "Median duration",
    value: { value: "1.5s", suffix: null },
    trend: null,
    note: "Couldn't measure this now. Last measured 02/09/2026, 09:14.",
  },
};

/** No snapshot is readable by this viewer; a missing measurement is not zero. */
export const NotMeasured: Story = {
  args: { title: "Revenue at risk", value: null, trend: null },
};
