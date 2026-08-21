import type { EvidenceCardData } from "@posthog/ui/features/editor/evidencePreview";
import { PostHogObjectPageView } from "@posthog/ui/features/posthog-objects/PostHogObjectPage";
import type { Meta, StoryObj } from "@storybook/react-vite";

const DAYS = [
  "2026-08-10",
  "2026-08-11",
  "2026-08-12",
  "2026-08-13",
  "2026-08-14",
  "2026-08-15",
  "2026-08-16",
];

const flagPreview: EvidenceCardData = {
  title: "pi-harness",
  detail: "Cloud task harness rollout",
  status: { label: "Enabled", tone: "positive" },
  stats: [
    { label: "Rollout", value: "100%" },
    { label: "Variants", value: "3" },
    { label: "Type", value: "Multivariate" },
    { label: "Calls in 7 days", value: "1.2K" },
  ],
  spark: { points: [24, 32, 28, 46, 51, 63, 58], labels: DAYS, render: "line" },
  sections: [
    {
      title: "Configuration",
      fields: [
        { label: "Type", value: "Multivariate" },
        { label: "Release conditions", value: "2 conditions" },
        { label: "Evaluation runtime", value: "Both client and server" },
        { label: "Last called", value: "Aug 16" },
      ],
    },
    {
      title: "Release conditions",
      fields: [
        { label: "Set 1", value: "plan is pro · 25% rollout · Variant: test" },
        { label: "Set 2", value: "75% rollout" },
      ],
    },
  ],
};

const experimentPreview: EvidenceCardData = {
  title: "Upgrade prompt experiment",
  detail: "Day 28 · Started Jul 24",
  status: { label: "Running", tone: "positive" },
  stats: [
    { label: "Running for", value: "28 days" },
    { label: "control exposed", value: "578" },
    { label: "aggressive exposed", value: "593" },
    { label: "subtle exposed", value: "563" },
  ],
  chart: {
    title: "Daily exposed users by variant",
    labels: DAYS,
    series: [
      { label: "control", data: [40, 44, 39, 47, 52, 49, 55] },
      { label: "aggressive", data: [38, 45, 41, 44, 50, 47, 52] },
      { label: "subtle", data: [36, 40, 42, 41, 47, 45, 49] },
    ],
    render: "line",
  },
  sections: [
    {
      title: "Configuration",
      fields: [
        {
          label: "Hypothesis",
          value: "A softer upgrade prompt converts more users.",
        },
        { label: "Feature flag", value: "upgrade-prompt-v1" },
        { label: "Variants", value: "34/33/33" },
        { label: "Created", value: "Jul 24" },
      ],
    },
    {
      title: "Metrics",
      fields: [
        { label: "Metric 1", value: "Login to upload" },
        { label: "Metric 2", value: "Downloads per user" },
      ],
    },
    {
      title: "Variants",
      fields: [
        { label: "control", value: "34% rollout" },
        { label: "aggressive", value: "33% rollout" },
        { label: "subtle", value: "33% rollout" },
      ],
    },
  ],
};

const meta: Meta<typeof PostHogObjectPageView> = {
  title: "Features/PostHog objects/PostHogObjectPageView",
  component: PostHogObjectPageView,
  parameters: { layout: "fullscreen" },
};

export default meta;
type Story = StoryObj<typeof PostHogObjectPageView>;

export const FeatureFlag: Story = {
  args: {
    objectKind: "flag",
    objectId: "390",
    fallbackName: "pi-harness",
    url: "https://us.posthog.com/project/2/feature_flags/390",
    occurrenceCount: 4,
    state: "ready",
    preview: flagPreview,
  },
};

export const Experiment: Story = {
  args: {
    objectKind: "experiment",
    objectId: "5",
    fallbackName: "Upgrade prompt experiment",
    url: "https://us.posthog.com/project/2/experiments/5",
    occurrenceCount: 5,
    state: "ready",
    preview: experimentPreview,
  },
};

export const SqlQuery: Story = {
  args: {
    objectKind: "hogql",
    objectId: "SELECT count() FROM events WHERE event = '$pageview'",
    fallbackName: "Total pageviews",
    url: "https://us.posthog.com/project/2/sql?open_query=SELECT+1",
    state: "ready",
    preview: null,
  },
};

export const Loading: Story = {
  args: {
    objectKind: "flag",
    objectId: "390",
    fallbackName: "pi-harness",
    url: null,
    occurrenceCount: 4,
    state: "loading",
    preview: null,
  },
};

export const MissingObject: Story = {
  args: {
    objectKind: "flag",
    objectId: "does-not-exist",
    fallbackName: "does-not-exist",
    url: null,
    occurrenceCount: 1,
    state: "missing",
    preview: null,
  },
};
