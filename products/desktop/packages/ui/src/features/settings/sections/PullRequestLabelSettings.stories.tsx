import type { SignalTeamConfig } from "@posthog/shared/types";
import { PullRequestLabelSettings } from "@posthog/ui/features/settings/sections/PullRequestLabelSettings";
import type { Meta, StoryObj } from "@storybook/react-vite";

function config(overrides: Partial<SignalTeamConfig> = {}): SignalTeamConfig {
  return {
    id: "config-1",
    default_autostart_priority: "P2",
    pull_request_label_enabled: false,
    pull_request_label: null,
    created_at: "2026-09-20T00:00:00Z",
    updated_at: "2026-09-20T00:00:00Z",
    ...overrides,
  } as SignalTeamConfig;
}

const meta: Meta<typeof PullRequestLabelSettings> = {
  title: "Self-driving/Pull request label",
  component: PullRequestLabelSettings,
  decorators: [
    (Story) => (
      <div className="mx-auto max-w-2xl p-6">
        <Story />
      </div>
    ),
  ],
  args: {
    config: config(),
    onSave: async () => {},
  },
};

export default meta;
type Story = StoryObj<typeof PullRequestLabelSettings>;

export const Off: Story = {};

export const OnWithDefaultLabel: Story = {
  args: { config: config({ pull_request_label_enabled: true }) },
};

export const OnWithCustomLabel: Story = {
  args: {
    config: config({
      pull_request_label_enabled: true,
      pull_request_label: "release-bot",
    }),
  },
};

export const Loading: Story = {
  args: { isLoading: true },
};
