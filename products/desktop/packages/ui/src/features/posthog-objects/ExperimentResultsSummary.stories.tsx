import type { ExperimentResultsPresentation } from "@posthog/api-client/evidence-previews";
import { ExperimentResultsSummary } from "@posthog/ui/features/posthog-objects/ExperimentResultsSummary";
import type { Meta, StoryObj } from "@storybook/react-vite";

const results: ExperimentResultsPresentation = {
  state: "ready",
  stale: false,
  lastRefresh: "2026-08-16T12:00:00Z",
  primaryMetrics: [
    {
      id: "checkout-conversion",
      name: "Checkout conversion",
      metricType: "primary",
      state: "ready",
      error: null,
      outcomeLabel: "Conversions",
      axisRange: 0.4,
      bestVariant: {
        key: "test",
        uplift: "+34.0%",
        significance: "significant",
        isImprovement: true,
      },
      variants: [
        {
          key: "control",
          isControl: true,
          outcome: "312 · 6.00%",
          sampleContext: "5.2K samples · 5.3K exposed",
          uplift: null,
          upliftValue: null,
          intervalBounds: null,
          upliftDirection: null,
          isImprovement: null,
          interval: null,
          pValue: null,
          chanceToWin: null,
          significance: null,
        },
        {
          key: "test",
          isControl: false,
          outcome: "410 · 8.04%",
          sampleContext: "5.1K samples · 5.2K exposed",
          uplift: "+34.0%",
          upliftValue: 0.34,
          intervalBounds: [0.011, 0.049],
          upliftDirection: "positive",
          isImprovement: true,
          interval: "+1.10% to +4.90%",
          pValue: "0.003",
          chanceToWin: null,
          significance: "significant",
        },
      ],
    },
  ],
  secondaryMetrics: [
    {
      id: "orders-per-user",
      name: "Orders per user",
      metricType: "secondary",
      state: "insufficient_data",
      error: null,
      outcomeLabel: "Outcome",
      axisRange: null,
      bestVariant: null,
      variants: [],
    },
  ],
};

const sampleMetric = results.primaryMetrics[0];
if (!sampleMetric) {
  throw new Error("The experiment results story needs one sample metric.");
}
const manyResults: ExperimentResultsPresentation = {
  ...results,
  primaryMetrics: [sampleMetric],
  secondaryMetrics: [
    "Activation rate",
    "Files uploaded",
    "Invites sent",
    "Seven-day retention",
    "Revenue per user",
    "Support requests",
  ].map((name, index) => ({
    ...sampleMetric,
    id: `secondary-${index}`,
    name,
    metricType: "secondary" as const,
    bestVariant: {
      key: "test",
      uplift: "+34.0%",
      significance: index === 2 ? "significant" : "not_significant",
      isImprovement: true,
    },
  })),
};

const meta: Meta<typeof ExperimentResultsSummary> = {
  title: "Features/PostHog objects/ExperimentResultsSummary",
  component: ExperimentResultsSummary,
  decorators: [
    (Story) => (
      <div className="max-w-4xl p-4">
        <Story />
      </div>
    ),
  ],
};

export default meta;
type Story = StoryObj<typeof ExperimentResultsSummary>;

export const Full: Story = {
  args: { display: "full", loadState: "ready", results },
};

export const Compact: Story = {
  args: { display: "compact", loadState: "ready", results },
  decorators: [
    (Story) => (
      <div className="w-80">
        <Story />
      </div>
    ),
  ],
};

export const ManyMetrics: Story = {
  args: { display: "full", loadState: "ready", results: manyResults },
};

export const Stale: Story = {
  args: {
    display: "full",
    loadState: "ready",
    results: { ...results, stale: true },
  },
};

export const Loading: Story = {
  args: { display: "full", loadState: "loading", results: null },
};
