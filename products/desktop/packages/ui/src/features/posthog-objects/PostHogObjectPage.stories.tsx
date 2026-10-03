import {
  ANONYMOUS_AUTH_STATE,
  useAuthStore,
} from "@posthog/ui/features/auth/store";
import { PostHogObjectPage } from "@posthog/ui/features/posthog-objects/PostHogObjectPage";
import type { Meta, StoryObj } from "@storybook/react-vite";

const meta: Meta<typeof PostHogObjectPage> = {
  title: "Features/PostHog objects/PostHogObjectPage",
  component: PostHogObjectPage,
  parameters: { layout: "fullscreen" },
  decorators: [
    (Story) => {
      useAuthStore.setState({
        authState: {
          ...ANONYMOUS_AUTH_STATE,
          cloudRegion: "us",
          currentProjectId: 2,
        },
      });
      return <Story />;
    },
  ],
};

export default meta;
type Story = StoryObj<typeof PostHogObjectPage>;

export const InsightReference: Story = {
  args: {
    fallbackName: "Checkout funnel",
    metadata: {
      reference_type: "posthog_object",
      object_kind: "insight",
      object_id: "9pQx3",
      source_message_ids: ["turn-1"],
      occurrence_count: 2,
    },
  },
};
