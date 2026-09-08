import type { Meta, StoryObj } from "@storybook/react-vite";
import { OnboardingLanding } from "./OnboardingLanding";

const meta = {
  title: "Onboarding/OnboardingLanding",
  component: OnboardingLanding,
  args: {
    selfDrivingAvailable: true,
    onOpenDestination: () => {},
  },
  parameters: {
    layout: "fullscreen",
  },
} satisfies Meta<typeof OnboardingLanding>;

export default meta;
type Story = StoryObj<typeof meta>;

export const Default: Story = {};

export const NarrowScene: Story = {
  decorators: [
    (Story) => (
      <div className="h-screen w-[520px]">
        <Story />
      </div>
    ),
  ],
};
