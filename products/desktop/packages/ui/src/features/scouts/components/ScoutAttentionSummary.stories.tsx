import type { ScoutConfig } from "@posthog/api-client/posthog-client";
import type { ScoutAttention } from "@posthog/core/scouts/scoutPresentation";
import type { Meta, StoryObj } from "@storybook/react-vite";
import { ScoutAttentionSummary } from "./ScoutAttentionSummary";

// Invented agents for an invented fleet.
function item(
  skillName: string,
  kind: ScoutAttention["kind"],
  detail: string,
): ScoutAttention {
  return {
    kind,
    detail,
    config: {
      id: skillName,
      skill_name: skillName,
      enabled: kind !== "auto_paused",
      emit: true,
      run_interval_minutes: 60,
      last_run_at: null,
      created_at: "2026-06-01T00:00:00Z",
    } as ScoutConfig,
  };
}

const PAUSED = "Nobody acted on its signals.";
const SOON = "3 runs in a row failed. PostHog pauses it soon.";

const meta = {
  title: "Scouts/ScoutAttentionSummary",
  component: ScoutAttentionSummary,
  parameters: { layout: "centered" },
} satisfies Meta<typeof ScoutAttentionSummary>;

export default meta;
type Story = StoryObj<typeof meta>;

export const AFewAgents: Story = {
  args: {
    items: [
      item("signals-scout-error-tracking", "auto_paused", PAUSED),
      item("signals-scout-web-vitals", "auto_paused", PAUSED),
      item("signals-scout-surveys", "pausing_soon", SOON),
    ],
  },
};

export const MoreThanTheCap: Story = {
  args: {
    items: Array.from({ length: 11 }, (_, index) =>
      item(`signals-scout-area-${index + 1}`, "auto_paused", PAUSED),
    ),
  },
};
