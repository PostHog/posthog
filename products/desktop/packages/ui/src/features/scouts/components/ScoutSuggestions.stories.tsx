import type {
  ScoutConfig,
  ScoutSuggestionItem,
} from "@posthog/api-client/posthog-client";
import { AgentsTabLayout } from "@posthog/ui/features/agents/components/AgentsTabLayout";
import type { Meta, StoryObj } from "@storybook/react-vite";
import { ScoutSuggestions } from "./ScoutSuggestions";

// Invented suggestions for an invented project.
const ITEMS: ScoutSuggestionItem[] = [
  {
    id: "s1",
    kind: "canonical",
    skill_name: "signals-scout-web-vitals",
    title: "Watch web vitals on the pages people land on",
    why_here:
      "This project records web vitals, and the landing pages moved twice this month. Nothing in the fleet reads them yet.",
    description: "",
    draft_body: "",
    proposed_config: {
      run_cron_schedule: "0 9 * * *",
      run_interval_minutes: null,
      emit: true,
    },
    gap: true,
    confidence: "high",
  },
  {
    id: "s2",
    kind: "canonical",
    skill_name: "signals-scout-revenue-analytics",
    title: "Watch revenue for a drop against its own baseline",
    why_here:
      "Revenue events arrive every day, and this agent already exists on the project with its switch off.",
    description: "",
    draft_body: "",
    proposed_config: {
      run_cron_schedule: null,
      run_interval_minutes: 720,
      emit: true,
    },
    gap: false,
    confidence: "medium",
  },
  {
    id: "s3",
    kind: "custom",
    skill_name: "signals-scout-checkout-abandonment",
    title: "Watch checkout abandonment after a deploy",
    why_here:
      "Checkout events and deploy markers both land here, and no agent reads them together.",
    description:
      "Compare checkout completion in the hour after each deploy against the day before.",
    draft_body: "# Checkout abandonment after a deploy…",
    proposed_config: {
      run_cron_schedule: null,
      run_interval_minutes: 180,
      emit: false,
    },
    gap: true,
    confidence: "medium",
  },
];

const CONFIGS: ScoutConfig[] = [
  {
    id: "config-web-vitals",
    skill_name: "signals-scout-web-vitals",
    enabled: false,
    emit: true,
    scout_origin: "canonical",
    run_interval_minutes: 1440,
    created_at: "2026-06-01T00:00:00Z",
  },
  {
    id: "config-revenue",
    skill_name: "signals-scout-revenue-analytics",
    enabled: false,
    emit: true,
    scout_origin: "canonical",
    run_interval_minutes: 720,
    created_at: "2026-06-01T00:00:00Z",
  },
];

const noop = () => undefined;

const meta = {
  title: "Scouts/ScoutSuggestions",
  component: ScoutSuggestions,
  parameters: { layout: "fullscreen" },
  args: {
    items: ITEMS,
    configs: CONFIGS,
    onTurnOn: noop,
    onDraft: noop,
    onDismiss: noop,
  },
  decorators: [
    (Story) => (
      <div className="h-[30rem]">
        <AgentsTabLayout tab="agents" fill count={2}>
          <Story />
        </AgentsTabLayout>
      </div>
    ),
  ],
} satisfies Meta<typeof ScoutSuggestions>;

export default meta;

type Story = StoryObj<typeof meta>;

/** What PostHog would add to this project, and why it thinks so. */
export const Suggested: Story = {};
