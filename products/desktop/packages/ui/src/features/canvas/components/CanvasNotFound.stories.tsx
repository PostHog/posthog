import type { Meta, StoryObj } from "@storybook/react-vite";
import { CanvasNotFound } from "./CanvasNotFound";

/**
 * A share link opened against a project that does not have the canvas. The channel lookup goes
 * through tRPC, which never resolves in Storybook, so this renders the branch where the channel
 * is absent too, which is what a cross-project link actually hits.
 */
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
