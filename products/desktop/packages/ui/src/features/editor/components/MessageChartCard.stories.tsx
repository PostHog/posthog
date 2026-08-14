import { MarkdownRenderer } from "@posthog/ui/features/editor/components/MarkdownRenderer";
import { MessageChartCard } from "@posthog/ui/features/editor/components/MessageChartCard";
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

const DAU_BLOCK = JSON.stringify({
  title: "Daily active users",
  caption: "Weekends dip to roughly half of weekday traffic.",
  render: "bar",
  labels: ["Aug 7", "Aug 8", "Aug 9", "Aug 10", "Aug 11", "Aug 12", "Aug 13"],
  series: [
    { name: "DAU", points: [69650, 39431, 47804, 85174, 83213, 81434, 79541] },
  ],
});

const MULTI_BLOCK = JSON.stringify({
  title: "Signups vs activations",
  render: "line",
  labels: [
    "2026-08-08",
    "2026-08-09",
    "2026-08-10",
    "2026-08-11",
    "2026-08-12",
  ],
  series: [
    { name: "Signups", points: [420, 180, 510, 560, 540] },
    { name: "Activations", points: [210, 90, 260, 300, 310] },
  ],
});

export const InlineData: Story = {
  render: () => (
    <div className="max-w-xl">
      <MessageChartCard
        spec={{
          mode: "data",
          title: "Daily active users",
          render: "bar",
          labels: ["Aug 7", "Aug 8", "Aug 9", "Aug 10"],
          series: [{ name: "DAU", points: [69650, 39431, 47804, 85174] }],
        }}
        blockKey="story-inline"
      />
    </div>
  ),
};

export const InsideAgentMessage: Story = {
  render: () => (
    <div className="max-w-xl">
      <MarkdownRenderer
        content={[
          "Here's the daily active user count for the last 7 days:",
          "",
          "```posthog-chart",
          DAU_BLOCK,
          "```",
          "",
          "**Weekday vs. weekend pattern** is very clear, with Mon-Thu holding 79K-85K.",
          "",
          "```posthog-chart",
          MULTI_BLOCK,
          "```",
        ].join("\n")}
      />
    </div>
  ),
};
