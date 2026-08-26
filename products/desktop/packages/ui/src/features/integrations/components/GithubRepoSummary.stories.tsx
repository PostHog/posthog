import { Button } from "@posthog/quill";
import { GithubRepoSummary } from "@posthog/ui/features/integrations/components/GithubRepoSummary";
import { SettingsCard } from "@posthog/ui/features/settings/components/SettingsCard";
import type { Meta, StoryObj } from "@storybook/react-vite";

const repos = [
  "posthog/posthog",
  "posthog/posthog-js",
  "posthog/posthog.com",
  "posthog/posthog-python",
  "posthog/code",
];

const meta: Meta<typeof GithubRepoSummary> = {
  title: "Integrations/GithubRepoSummary",
  component: GithubRepoSummary,
  parameters: { layout: "padded" },
  decorators: [
    (Story) => (
      <SettingsCard>
        <Story />
      </SettingsCard>
    ),
  ],
  args: {
    accountLabel: "PostHog",
    repos,
    status: "connected",
    meta: "Connected 3 days ago",
    onManage: () => {},
    actions: (
      <Button variant="outline" size="sm" className="text-(--red-11)">
        Disconnect
      </Button>
    ),
  },
};

export default meta;
type Story = StoryObj<typeof GithubRepoSummary>;

export const SelectedRepositories: Story = {
  args: {
    summary: { kind: "selected", label: "5 selected repositories" },
  },
};

export const AllRepositories: Story = {
  args: {
    summary: { kind: "all", label: "All repositories in PostHog (712)" },
  },
};

export const NoRepositories: Story = {
  args: {
    repos: [],
    summary: { kind: "empty", label: "No repositories accessible" },
  },
};

export const LoadingRepositories: Story = {
  args: {
    repos: [],
    isLoadingRepos: true,
    summary: { kind: "unknown", label: "" },
  },
};

export const RemovedFromGithub: Story = {
  args: {
    status: "unavailable",
    summary: { kind: "selected", label: "5 selected repositories" },
    actions: (
      <Button variant="outline" size="sm" className="text-(--red-11)">
        Remove
      </Button>
    ),
  },
};

export const PlaceholderAccountName: Story = {
  args: {
    accountLabel: "GitHub installation 152736578",
    summary: { kind: "unknown", label: "5 repositories accessible" },
  },
};
