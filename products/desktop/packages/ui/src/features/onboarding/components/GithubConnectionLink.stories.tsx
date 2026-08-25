import { GithubConnectionLink } from "@posthog/ui/features/onboarding/components/GithubConnectionLink";
import type { Meta, StoryObj } from "@storybook/react-vite";

const meta: Meta<typeof GithubConnectionLink> = {
  title: "Onboarding/GithubConnectionLink",
  component: GithubConnectionLink,
};
export default meta;

type Story = StoryObj<typeof GithubConnectionLink>;

export const Disconnected: Story = { args: { connected: false } };
export const Connected: Story = {
  args: { connected: true, accountLabel: "Connected as adboio" },
};
