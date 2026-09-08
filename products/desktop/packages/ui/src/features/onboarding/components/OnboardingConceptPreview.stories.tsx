import type { OnboardingLandingDestination } from "@posthog/shared/analytics-events";
import type { Meta, StoryObj } from "@storybook/react-vite";
import { OnboardingConceptPreview } from "./OnboardingConceptPreview";

const meta = {
  title: "Onboarding/OnboardingConceptPreview",
  component: OnboardingConceptPreview,
  args: {
    destination: "spaces",
  },
} satisfies Meta<typeof OnboardingConceptPreview>;

export default meta;
type Story = StoryObj<typeof meta>;

export const Spaces: Story = {
  decorators: [
    (Story) => (
      <div className="w-[420px] overflow-hidden">
        <Story />
      </div>
    ),
  ],
};

export const AllConcepts: Story = {
  decorators: [
    (Story) => (
      <div className="grid w-[860px] grid-cols-2 gap-4">
        <Story />
      </div>
    ),
  ],
  render: () => {
    const destinations: OnboardingLandingDestination[] = [
      "spaces",
      "self-driving",
      "canvases",
      "agents",
      "tasks",
    ];
    return destinations.map((destination) => (
      <div
        key={destination}
        className="overflow-hidden rounded-(--radius-3) border border-border"
      >
        <OnboardingConceptPreview destination={destination} />
      </div>
    ));
  },
};
