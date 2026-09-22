import type { Meta, StoryObj } from "@storybook/react-vite";
import { UsageLimitModalContent } from "./UsageLimitModal";

const meta: Meta<typeof UsageLimitModalContent> = {
  title: "Billing/Usage limit modal",
  component: UsageLimitModalContent,
  args: {
    open: true,
    onDismiss: () => {},
    onAction: () => {},
  },
};

export default meta;
type Story = StoryObj<typeof UsageLimitModalContent>;

export const OrganizationAdmin: Story = {
  args: {
    content: {
      title: "Organization usage limit reached",
      description:
        "Your organization has reached its PostHog Desktop credit limit. Change the limit in Plan & usage to keep going.",
      actionLabel: "Open Plan & usage",
      dismissLabel: "Got it",
    },
  },
};

export const OrganizationMember: Story = {
  args: {
    content: {
      title: "Organization usage limit reached",
      description:
        "Your organization has reached its PostHog Desktop credit limit. Contact an organization administrator to change the limit.",
      actionLabel: null,
      dismissLabel: "Got it",
    },
  },
};

export const ProviderRateLimit: Story = {
  args: {
    content: {
      title: "Usage limit reached",
      description:
        "This app hit a usage limit. Resets in 12 minutes. Please try again shortly.",
      actionLabel: null,
      dismissLabel: "Got it",
    },
  },
};
