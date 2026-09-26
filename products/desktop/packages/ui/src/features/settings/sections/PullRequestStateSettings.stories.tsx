import type {
  SignalTeamConfig,
  SignalUserAutonomyConfig,
} from "@posthog/shared/types";
import { PullRequestStateSettings } from "@posthog/ui/features/settings/sections/PullRequestStateSettings";
import type { Meta, StoryObj } from "@storybook/react-vite";
import { useState } from "react";

const meta: Meta<typeof PullRequestStateSettings> = {
  title: "Settings/PullRequestStateSettings",
  component: PullRequestStateSettings,
  decorators: [
    (Story) => (
      <div style={{ maxWidth: 800, margin: "2rem auto", padding: "0 1.5rem" }}>
        <Story />
      </div>
    ),
  ],
};

export default meta;
type Story = StoryObj<typeof PullRequestStateSettings>;

const BASE_TEAM_CONFIG: SignalTeamConfig = {
  id: "team-config",
  default_autostart_priority: "P2",
  created_at: "2026-09-11T00:00:00Z",
  updated_at: "2026-09-11T00:00:00Z",
};

function InteractiveStory({
  teamReady,
  mine,
}: {
  teamReady: boolean;
  mine: boolean | null;
}) {
  const [teamConfig, setTeamConfig] = useState<SignalTeamConfig>({
    ...BASE_TEAM_CONFIG,
    default_open_pull_request_ready: teamReady,
  });
  const [userConfig, setUserConfig] = useState<SignalUserAutonomyConfig>({
    autostart_priority: null,
    github_open_pull_request_ready: mine,
  });

  return (
    <PullRequestStateSettings
      teamConfig={teamConfig}
      userConfig={userConfig}
      onSaveTeamDefault={async (ready) => {
        setTeamConfig((previous) => ({
          ...previous,
          default_open_pull_request_ready: ready,
        }));
      }}
      onSaveMine={async (ready) => {
        setUserConfig((previous) => ({
          ...previous,
          github_open_pull_request_ready: ready,
        }));
      }}
    />
  );
}

export const FollowingProject: Story = {
  render: () => <InteractiveStory teamReady={false} mine={null} />,
};

export const MyOverride: Story = {
  render: () => <InteractiveStory teamReady mine={false} />,
};

export const Loading: Story = {
  args: {
    teamConfig: null,
    userConfig: null,
    onSaveTeamDefault: async () => {},
    onSaveMine: async () => {},
    isLoading: true,
  },
};
