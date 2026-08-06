import type { SignalReportChart } from "@posthog/shared/types";
import type { Meta, StoryObj } from "@storybook/react-vite";
import { SignalReportSummaryMarkdown } from "./SignalReportSummaryMarkdown";

// SavedInsightNode charts render as link-only cards, so the placement rules
// are visible without any query round-trip.
const CHARTS: SignalReportChart[] = [
  {
    chart_id: "signups-drop",
    title: "Daily signups",
    query: { kind: "SavedInsightNode", shortId: "abc123" },
    caption: "The drop starts on the 4th.",
  },
  {
    chart_id: "churn",
    title: "Churn trend",
    query: { kind: "SavedInsightNode", shortId: "def456" },
  },
];

const SUMMARY = [
  "Signups **dropped 30%** after the pricing page release.",
  "[Daily signups](chart:signups-drop)",
  "The [churn trend](chart:churn) reference sits in prose, so it stays text and its chart renders after the summary instead.",
  "- Affected surface: the pricing page\n- First seen: 2026-07-04",
].join("\n\n");

const meta: Meta<typeof SignalReportSummaryMarkdown> = {
  title: "Inbox/SignalReportSummaryMarkdown",
  component: SignalReportSummaryMarkdown,
  decorators: [
    (Story) => (
      <div style={{ maxWidth: 640, margin: "2rem auto", padding: "0 1rem" }}>
        <Story />
      </div>
    ),
  ],
};
export default meta;
type Story = StoryObj<typeof SignalReportSummaryMarkdown>;

/**
 * Detail variant with charts: the reference standing alone in its paragraph
 * draws a chart card at that point; the reference inside prose stays text.
 */
export const DetailWithChartRefs: Story = {
  args: {
    content: SUMMARY,
    fallback: "No summary yet.",
    variant: "detail",
    reportId: "report-1",
    charts: CHARTS,
  },
};

/** List rows never draw charts; a chart reference reads as its label. */
export const ListRowWithChartRef: Story = {
  args: {
    content: "Signups dropped, see [Daily signups](chart:signups-drop).",
    fallback: "No summary yet.",
    variant: "list",
  },
};

export const DetailPending: Story = {
  args: {
    content: null,
    fallback: "No summary yet – the agent is still investigating.",
    variant: "detail",
    pending: true,
  },
};
