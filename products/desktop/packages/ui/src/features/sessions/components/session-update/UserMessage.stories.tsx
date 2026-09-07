import { UserMessage } from "@posthog/ui/features/sessions/components/session-update/UserMessage";
import type { Meta, StoryObj } from "@storybook/react-vite";

const meta: Meta<typeof UserMessage> = {
  title: "Features/Sessions/UserMessage",
  component: UserMessage,
  decorators: [
    (Story) => (
      <div className="max-w-2xl p-6">
        <Story />
      </div>
    ),
  ],
};

export default meta;
type Story = StoryObj<typeof UserMessage>;

const FIXED_TIMESTAMP = Date.parse("2026-07-01T10:30:00Z");

export const Typed: Story = {
  args: {
    content: "What are our top errors this week?",
    timestamp: FIXED_TIMESTAMP,
    animate: false,
  },
};

// The first-run session's whole prompt is an <onboarding_brief> block, so the bubble strips to
// nothing and the chip is all the reader has while the agent's first turn streams.
export const OnboardingBrief: Story = {
  args: {
    content:
      "<onboarding_brief>\nWrite the first message someone sees in PostHog Desktop.\n</onboarding_brief>",
    timestamp: FIXED_TIMESTAMP,
    animate: false,
  },
};
