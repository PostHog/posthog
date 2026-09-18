import { ActivityDetailCloseButton } from "@posthog/ui/features/canvas/components/ActivityDetailCloseButton";
import type { Meta, StoryObj } from "@storybook/react-vite";

const meta: Meta<typeof ActivityDetailCloseButton> = {
  title: "Canvas/Activity/Detail close button",
  component: ActivityDetailCloseButton,
  parameters: { layout: "centered" },
};

export default meta;
type Story = StoryObj<typeof ActivityDetailCloseButton>;

export const Default: Story = {};
