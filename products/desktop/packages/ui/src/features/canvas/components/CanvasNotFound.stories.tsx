import type { Meta, StoryObj } from "@storybook/react-vite";
import { CanvasNotFound } from "./CanvasNotFound";

const meta = {
  title: "Canvas/CanvasNotFound",
  component: CanvasNotFound,
  parameters: { layout: "fullscreen" },
  decorators: [
    (Story) => (
      <div className="h-100">
        <Story />
      </div>
    ),
  ],
} satisfies Meta<typeof CanvasNotFound>;

export default meta;
type Story = StoryObj<typeof meta>;

export const Default: Story = {
  args: { channelId: "chan-1" },
};
