import { GithubConnectionRequiredDialog } from "@posthog/ui/features/integrations/components/GithubConnectionRequiredDialog";
import type { Meta, StoryObj } from "@storybook/react-vite";

const meta: Meta<typeof GithubConnectionRequiredDialog> = {
  title: "Integrations/GithubConnectionRequiredDialog",
  component: GithubConnectionRequiredDialog,
};
export default meta;

type Story = StoryObj<typeof GithubConnectionRequiredDialog>;

export const Default: Story = {
  args: {
    open: true,
    isConnecting: false,
    canRunLocally: true,
    onOpenChange: () => undefined,
    onConnect: () => undefined,
    onRunLocally: () => undefined,
  },
};

export const PendingApproval: Story = {
  args: {
    ...Default.args,
    approvalPending: true,
    connectionMessage:
      "GitHub sent your request to your organization owners. Once an owner approves the PostHog app, we'll finish connecting here.",
  },
};
