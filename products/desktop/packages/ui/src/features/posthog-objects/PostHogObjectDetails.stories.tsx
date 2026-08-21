import type { EvidencePreview } from "@posthog/api-client/evidence-previews";
import { PostHogObjectDetails } from "@posthog/ui/features/posthog-objects/PostHogObjectDetails";
import type { Meta, StoryObj } from "@storybook/react-vite";

const preview: EvidencePreview = {
  title: "Checkout rollout",
  spark: { points: [24, 32, 28, 46, 51, 63, 58], render: "line" },
  sections: [
    {
      title: "Configuration",
      fields: [
        { label: "State", value: "Enabled" },
        { label: "Type", value: "Multivariate" },
        { label: "Release conditions", value: "2 conditions" },
        { label: "Evaluation runtime", value: "Both client and server" },
      ],
    },
    {
      title: "Activity",
      fields: [
        { label: "Calls in 7 days", value: "302" },
        { label: "Staleness", value: "Active" },
      ],
    },
  ],
};

const meta: Meta<typeof PostHogObjectDetails> = {
  title: "Features/PostHog objects/PostHogObjectDetails",
  component: PostHogObjectDetails,
  parameters: { layout: "padded" },
};

export default meta;
type Story = StoryObj<typeof PostHogObjectDetails>;

export const WithActivity: Story = {
  args: { preview },
};

export const DetailsOnly: Story = {
  args: {
    preview: {
      ...preview,
      spark: undefined,
    },
  },
};
