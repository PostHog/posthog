import type { Meta, StoryObj } from "@storybook/react-vite";
import { FeedbackModal } from "./FeedbackModal";

const meta = {
  title: "Feedback/Desktop feedback modal",
  component: FeedbackModal,
  args: {
    mode: "feedback",
    onFinished: () => {},
  },
} satisfies Meta<typeof FeedbackModal>;

export default meta;
type Story = StoryObj<typeof meta>;

export const Default: Story = {};
