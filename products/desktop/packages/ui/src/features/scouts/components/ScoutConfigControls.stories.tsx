import type { ScoutConfig } from "@posthog/api-client/posthog-client";
import type { Meta, StoryObj } from "@storybook/react-vite";
import { ScoutConfigForm } from "./ScoutConfigControls";

const CONFIG: ScoutConfig = {
  id: "config-checkout-funnel",
  skill_name: "signals-scout-checkout-funnel",
  enabled: true,
  emit: true,
  scout_origin: "custom",
  run_interval_minutes: 480,
  auto_pause_exempt: false,
  created_at: "2026-06-01T00:00:00Z",
  last_run_at: "2026-07-09T06:30:00Z",
  repository: "posthog/posthog",
  description: "Watches conversion through the checkout funnel.",
};

const meta = {
  title: "Scouts/ScoutConfigControls",
  component: ScoutConfigForm,
  parameters: { layout: "fullscreen" },
  args: {
    config: CONFIG,
    onUpdate: () => undefined,
  },
} satisfies Meta<typeof ScoutConfigForm>;

export default meta;

type Story = StoryObj<typeof meta>;

export const Settings: Story = {};
