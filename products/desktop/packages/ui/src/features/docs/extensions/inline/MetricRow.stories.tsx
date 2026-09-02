import type { Meta, StoryObj } from "@storybook/react-vite";
import { MetricTileView } from "../MetricRow";
import "@posthog/ui/features/docs/components/docs.css";

const SERIES = [820, 910, 870, 1040, 1180, 1120, 1310];

const meta: Meta<typeof MetricTileView> = {
  title: "Docs/Metric row",
  component: MetricTileView,
  decorators: [
    (Story) => (
      <div className="doc-body" style={{ maxWidth: 620, padding: 24 }}>
        <Story />
      </div>
    ),
  ],
};

export default meta;
type Story = StoryObj<typeof MetricTileView>;

/** A row as the reader meets it: two settled numbers, one still loading, one lost. */
export const Row: Story = {
  render: () => (
    <div className="doc-metrics">
      <MetricTileView
        label="Signups this week"
        value="1,310"
        series={SERIES}
        delta={0.17}
        isLoading={false}
        isError={false}
      />
      <MetricTileView
        label="Activation rate"
        value="41.2"
        series={[52, 49, 47, 44, 41]}
        delta={-0.068}
        isLoading={false}
        isError={false}
      />
      <MetricTileView
        label="Weekly revenue"
        value="—"
        series={null}
        delta={null}
        isLoading
        isError={false}
      />
      <MetricTileView
        label="Support tickets"
        value="—"
        series={null}
        delta={null}
        isLoading={false}
        isError
      />
    </div>
  ),
};
