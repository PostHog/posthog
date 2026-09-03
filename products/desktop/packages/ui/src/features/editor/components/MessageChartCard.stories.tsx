import { chartHeadlineStat } from "@posthog/core/inbox/reportCharts";
import { MarkdownRenderer } from "@posthog/ui/features/editor/components/MarkdownRenderer";
import { MessageChartCard } from "@posthog/ui/features/editor/components/MessageChartCard";
import { ReportChartCardView } from "@posthog/ui/features/inbox/components/detail/ReportChartCard";
import type { Meta, StoryObj } from "@storybook/react-vite";

const meta: Meta<typeof MessageChartCard> = {
  title: "Features/Editor/MessageChartCard",
  component: MessageChartCard,
  parameters: {
    layout: "padded",
  },
};

export default meta;
type Story = StoryObj<typeof MessageChartCard>;

/**
 * What a resolved chart card looks like: the query ran and came back as a
 * single series, so the header carries the headline value and step change.
 * (Storybook has no PostHog session, so the live-query stories below show
 * the loading state instead.)
 */
export const ResolvedCard: Story = {
  render: () => {
    const data = {
      type: "series" as const,
      render: "line" as const,
      labels: [
        "2026-08-07",
        "2026-08-08",
        "2026-08-09",
        "2026-08-10",
        "2026-08-11",
        "2026-08-12",
        "2026-08-13",
        "2026-08-14",
      ],
      series: [
        {
          key: "0:DAU",
          label: "DAU",
          data: [69650, 39431, 47804, 85174, 83213, 81434, 79541, 17100],
        },
      ],
      isTimeSeries: true,
      interval: "day" as const,
    };
    return (
      <div className="max-w-xl">
        <ReportChartCardView
          chartId="story-resolved"
          title="Daily active users, last 7 days"
          caption="The drop on Aug 14 lines up with the checkout deploy."
          heightClass="h-52"
          state={{ kind: "data", data }}
          openTarget={{ url: "https://example.com", label: "Open insight" }}
          stat={chartHeadlineStat(data)}
        />
      </div>
    );
  },
};

export const TagsInsideAgentMessage: Story = {
  render: () => (
    <div className="max-w-xl">
      <MarkdownRenderer
        content={[
          "Here's the daily active user count for the last 7 days:",
          "",
          '<hogql display="block" title="Daily active users, last 7 days" caption="The drop on Aug 14 lines up with the checkout deploy.">',
          "SELECT toDate(timestamp) AS day, count(DISTINCT person_id) AS dau",
          "FROM events WHERE timestamp >= now() - INTERVAL 7 DAY GROUP BY day ORDER BY day",
          "</hogql>",
          "",
          "**Weekday vs. weekend pattern** is very clear, with Mon-Thu holding 79K-85K.",
          "The same trend as the saved insight:",
          "",
          '<insight id="9pQx3" display="block"/>',
        ].join("\n")}
      />
    </div>
  ),
};
