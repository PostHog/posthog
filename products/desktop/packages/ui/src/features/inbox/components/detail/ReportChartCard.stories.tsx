import type { Meta, StoryObj } from "@storybook/react-vite";
import { ReportChartCard, SeriesChart } from "./ReportChartCard";

const DAYS = Array.from(
  { length: 14 },
  (_, i) => `2026-07-${String(i + 1).padStart(2, "0")}`,
);

const trend = (scale: number, wobble: number): number[] =>
  DAYS.map((_, i) =>
    Math.round(scale + i * 3 + Math.sin(i * wobble) * scale * 0.3),
  );

const meta: Meta<typeof SeriesChart> = {
  title: "Inbox/ReportChartCard",
  component: SeriesChart,
  decorators: [
    (Story) => (
      <div style={{ maxWidth: 640, margin: "2rem auto", padding: "0 1rem" }}>
        <Story />
      </div>
    ),
  ],
};
export default meta;
type Story = StoryObj<typeof SeriesChart>;

export const LineTwoSeries: Story = {
  args: {
    data: {
      series: [
        { label: "Signups", data: trend(40, 0.8) },
        { label: "Churns", data: trend(12, 1.3) },
      ],
      labels: DAYS,
      days: DAYS,
    },
    display: "line",
    heightClass: "h-56",
    title: "Signups vs churns",
  },
};

export const BarSingleSeries: Story = {
  args: {
    data: {
      series: [{ label: "Errors", data: trend(20, 1.1) }],
      labels: DAYS,
      days: DAYS,
    },
    display: "bar",
    heightClass: "h-56",
    title: "Errors per day",
  },
};

/**
 * A saved-insight chart has no query body to run, so the card explains where
 * it renders; without an authenticated client the open control is absent too.
 */
export const LinkOnlyCard: StoryObj<typeof ReportChartCard> = {
  render: () => (
    <ReportChartCard
      reportId="report-1"
      chart={{
        chart_id: "weekly-retention",
        title: "Weekly retention",
        query: { kind: "SavedInsightNode", shortId: "abc123" },
        caption: "Retention held steady through the release.",
      }}
    />
  ),
};
