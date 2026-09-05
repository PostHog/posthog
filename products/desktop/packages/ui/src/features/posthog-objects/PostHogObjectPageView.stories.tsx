import type { FlagAudience, FlagRule } from "@posthog/api-client/flag-audience";
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

const alex = {
  label: "Alex Rivera",
  secondary: "alex@example.com",
  raw: "4dc8564d-1f2e-4b7a-9c3d-2a1b0c9d8e7f",
  link: { kind: "person" as const, id: "4dc8564d-1f2e-4b7a-9c3d-2a1b0c9d8e7f" },
};

const betaTesters = {
  label: "Beta testers",
  raw: "142",
  link: { kind: "cohort" as const, id: "142" },
};

const rule = (overrides: Partial<FlagRule>): FlagRule => ({
  conditions: [],
  share: 100,
  result: { kind: "true" },
  reachable: true,
  isGroup: false,
  ...overrides,
});

const audience = (overrides: Partial<FlagAudience>): FlagAudience => ({
  headline: "On for everyone.",
  disabled: false,
  rules: [],
  fallbackReachable: true,
  variants: [],
  bucketing: "person",
  enrollmentKey: null,
  holdout: null,
  ...overrides,
});

const multivariateAudience = audience({
  headline: "Split into 3 variants for Alex Rivera and Pro plan users.",
  rules: [
    rule({
      conditions: [{ subject: "Person", operator: "is", values: [alex] }],
      result: { kind: "variant", key: "test" },
    }),
    rule({
      conditions: [
        { subject: "plan", operator: "is", values: [{ label: "pro" }] },
        { subject: "Cohort", operator: "in cohort", values: [betaTesters] },
      ],
      share: 25,
      result: { kind: "split" },
    }),
    rule({
      conditions: [
        {
          subject: "email",
          operator: "ends with",
          values: [{ label: "@example.com" }],
        },
      ],
      result: { kind: "variant", key: "control" },
    }),
  ],
  variants: [
    { key: "control", percentage: 34, payload: null },
    { key: "test", percentage: 33, payload: '{"prompt":"soft"}' },
    { key: "aggressive", percentage: 33, payload: '{"prompt":"hard"}' },
  ],
});

const configuration = {
  title: "Configuration",
  fields: [
    { label: "Type", value: "Multivariate" },
    { label: "Evaluation runtime", value: "All runtimes" },
    { label: "Experience continuity", value: "On" },
    { label: "Last called", value: "Aug 16" },
    {
      label: "Targeted IDs",
      value: "4dc8564d-1f2e-4b7a-9c3d-2a1b0c9d8e7f",
    },
  ],
};

const flagPreview: EvidenceCardData = {
  title: "pi-harness",
  detail: "Cloud task harness rollout",
  status: { label: "Enabled", tone: "positive" },
  stats: [
    { label: "Reach", value: "Alex Rivera and Pro plan users" },
    { label: "Variants", value: "3" },
    { label: "Type", value: "Multivariate" },
  ],
  spark: { points: [24, 32, 28, 46, 51, 63, 58], labels: DAYS, render: "line" },
  flagAudience: multivariateAudience,
  sections: [configuration],
};

const experimentPreview: EvidenceCardData = {
  title: "Upgrade prompt experiment",
  detail: "Day 28 · Started Jul 24",
  status: { label: "Running", tone: "positive" },
  experimentResults: {
    state: "ready",
    stale: false,
    lastRefresh: "2026-08-16T12:00:00Z",
    primaryMetrics: [
      {
        id: "login-to-upload",
        name: "Login to upload",
        metricType: "primary",
        state: "ready",
        error: null,
        outcomeLabel: "Conversions",
        axisRange: 0.35,
        bestVariant: {
          key: "aggressive",
          uplift: "+17.2%",
          significance: "significant",
          isImprovement: true,
        },
        variants: [
          {
            key: "control",
            isControl: true,
            outcome: "104 · 18.0%",
            sampleContext: "578 samples · 578 exposed",
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
            key: "aggressive",
            isControl: false,
            outcome: "125 · 21.1%",
            sampleContext: "593 samples · 593 exposed",
            uplift: "+17.2%",
            upliftValue: 0.172,
            intervalBounds: [0.021, 0.323],
            upliftDirection: "positive",
            isImprovement: true,
            interval: "+2.10% to +32.3%",
            pValue: "0.028",
            chanceToWin: null,
            significance: "significant",
          },
          {
            key: "subtle",
            isControl: false,
            outcome: "108 · 19.2%",
            sampleContext: "563 samples · 563 exposed",
            uplift: "+6.67%",
            upliftValue: 0.0667,
            intervalBounds: [-0.081, 0.214],
            upliftDirection: "positive",
            isImprovement: true,
            interval: "-8.10% to +21.4%",
            pValue: "0.380",
            chanceToWin: null,
            significance: "not_significant",
          },
        ],
      },
    ],
    secondaryMetrics: [],
  },
  stats: [
    { label: "Running for", value: "28 days" },
    { label: "control exposed", value: "578" },
    { label: "aggressive exposed", value: "593" },
    { label: "subtle exposed", value: "563" },
  ],
  chart: {
    title: "Daily exposures by variant",
    labels: DAYS,
    series: [
      { label: "control", data: [40, 44, 39, 47, 52, 49, 55] },
      { label: "aggressive", data: [38, 45, 41, 44, 50, 47, 52] },
      { label: "subtle", data: [36, 40, 42, 41, 47, 45, 49] },
    ],
    render: "bar",
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
    taskId: "task-1",
    url: "https://us.posthog.com/project/2/feature_flags/390",
    occurrenceCount: 4,
    state: "ready",
    preview: flagPreview,
  },
};

export const Survey: Story = {
  args: {
    objectKind: "survey",
    objectId: "0198a1c2-7d3e-4f5a-9b6c-1d2e3f4a5b6c",
    fallbackName: "Checkout survey",
    url: "https://us.posthog.com/project/2/surveys/0198a1c2",
    occurrenceCount: 2,
    state: "ready",
    preview: {
      title: "Checkout survey",
      detail: "Since Aug 1",
      status: { label: "Running", tone: "positive" },
      stats: [
        { label: "Shown", value: "1.4K" },
        { label: "Responses", value: "212" },
        { label: "Response rate", value: "15%" },
      ],
      flagAudience: audience({
        headline: "Shown to 25% of Beta testers.",
        rules: [
          rule({
            conditions: [
              {
                subject: "Cohort",
                operator: "in cohort",
                values: [betaTesters],
              },
            ],
            share: 25,
          }),
        ],
      }),
      displayConditions: [
        {
          subject: "URL",
          operator: "contains",
          values: [{ label: "/checkout" }],
        },
        { subject: "Device", operator: "is", values: [{ label: "Desktop" }] },
      ],
      sections: [
        {
          title: "Questions",
          fields: [
            { label: "Question 1", value: "How was checkout? (Rating)" },
            { label: "Question 2", value: "What would you change? (Open)" },
          ],
        },
      ],
    },
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
    preview: {
      title: "Total pageviews",
      chartData: { type: "number", value: 68831577 },
    },
  },
};

export const InsightChart: Story = {
  args: {
    objectKind: "insight",
    objectId: "9pQx3",
    fallbackName: "Checkout funnel",
    url: "https://us.posthog.com/project/2/insights/9pQx3",
    occurrenceCount: 2,
    state: "ready",
    preview: {
      title: "Checkout funnel",
      detail: "Daily unique visitors",
      headline: { value: "1.5M", delta: { direction: "down", label: "70%" } },
      spark: { points: [24, 32, 28, 46, 51, 63, 58], render: "line" },
      chartData: {
        type: "series",
        labels: DAYS,
        series: [
          { key: "series-0", label: "DAU", data: [24, 32, 28, 46, 51, 63, 58] },
        ],
        render: "line",
        isTimeSeries: true,
        interval: "day",
      },
    },
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
