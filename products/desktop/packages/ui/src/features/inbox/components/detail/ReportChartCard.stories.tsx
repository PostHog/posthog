import type { Meta, StoryObj } from "@storybook/react";
import { ReportChartCardView } from "./ReportChartCard";

const meta: Meta<typeof ReportChartCardView> = {
  title: "Inbox/ReportChartCard",
  component: ReportChartCardView,
  args: {
    chartId: "story-chart",
    title: "Daily query_wait_timeout exceptions",
    caption: "Counts spike after the 2026-08-02 deploy.",
    heightClass: "h-72",
    openTarget: {
      url: "https://us.posthog.com/project/2/sql?open_query=SELECT+1",
      label: "Open in SQL editor",
    },
    onOpenExternal: () => {},
  },
  decorators: [
    (Story) => (
      <div style={{ maxWidth: 640 }}>
        <Story />
      </div>
    ),
  ],
};
export default meta;

type Story = StoryObj<typeof ReportChartCardView>;

const days = ["2026-08-01", "2026-08-02", "2026-08-03", "2026-08-04"];

/** The dominant real-world shape: a HogQL day/count grid drawn as a line. */
export const TimeSeriesLine: Story = {
  args: {
    state: {
      kind: "data",
      data: {
        type: "series",
        render: "line",
        labels: days,
        series: [{ key: "s0", label: "errors", data: [5, 42, 31, 12] }],
        isTimeSeries: true,
        interval: "day",
      },
    },
  },
};

/** Multi-series pivot (date + breakdown + count) gets a legend. */
export const TimeSeriesBarBreakdown: Story = {
  args: {
    state: {
      kind: "data",
      data: {
        type: "series",
        render: "bar",
        labels: days,
        series: [
          { key: "s0", label: "Chrome", data: [5, 7, 6, 4] },
          { key: "s1", label: "Safari", data: [2, 3, 1, 2] },
        ],
        isTimeSeries: true,
        interval: "day",
      },
    },
  },
};

/** Categorical first column keeps string labels on a band axis. */
export const CategoricalBar: Story = {
  args: {
    state: {
      kind: "data",
      data: {
        type: "series",
        render: "bar",
        labels: ["granted", "partial", "denied"],
        series: [{ key: "s0", label: "count", data: [120, 14, 3] }],
        isTimeSeries: false,
        interval: "day",
      },
    },
  },
};

/** A single numeric cell renders as a headline number, sized small. */
export const SingleNumber: Story = {
  args: {
    heightClass: "max-h-36",
    state: { kind: "data", data: { type: "number", value: 1284 } },
  },
};

/** Non-graphical grids fall back to a scrolling table. */
export const Table: Story = {
  args: {
    heightClass: "max-h-72",
    state: {
      kind: "data",
      data: {
        type: "table",
        columns: ["path", "errors", "users"],
        rows: [
          ["/checkout", 42, 31],
          ["/onboarding", 17, 15],
          ["/settings", 3, 3],
        ],
      },
    },
  },
};

export const Loading: Story = {
  args: { state: { kind: "loading" } },
};

/** Query failed: message plus the open-in-PostHog escape hatch. */
export const QueryError: Story = {
  args: {
    heightClass: "max-h-72",
    state: {
      kind: "error",
      message:
        "Couldn't run the query behind this chart. Open it in PostHog to investigate.",
    },
  },
};

/** Query kinds the desktop app can't draw (funnels, saved insights, ...). */
export const LinkOutFallback: Story = {
  args: {
    heightClass: "max-h-72",
    state: { kind: "link-out" },
    openTarget: {
      url: "https://us.posthog.com/project/2/insights/abc123",
      label: "Open insight",
    },
  },
};

/** A fallback whose query is too large to link (no dead button). */
export const LinkOutWithoutTarget: Story = {
  args: {
    heightClass: "max-h-72",
    state: { kind: "link-out" },
    openTarget: null,
  },
};

export const EmptyResult: Story = {
  args: {
    heightClass: "max-h-72",
    state: { kind: "data", data: { type: "empty" } },
  },
};
