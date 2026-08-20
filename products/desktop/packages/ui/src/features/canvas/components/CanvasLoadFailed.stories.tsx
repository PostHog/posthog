import type { Meta, StoryObj } from "@storybook/react-vite";
import { CanvasLoadFailed } from "./CanvasLoadFailed";

/**
 * The canvas request failed outright, as opposed to resolving to nothing. Separate from
 * `CanvasNotFound` because retrying is worth offering here and never is there.
 */
const meta = {
  title: "Canvas/CanvasLoadFailed",
  component: CanvasLoadFailed,
  parameters: { layout: "fullscreen" },
  args: { onRetry: () => {} },
  decorators: [
    (Story) => (
      <div className="h-100">
        <Story />
      </div>
    ),
  ],
} satisfies Meta<typeof CanvasLoadFailed>;

export default meta;
type Story = StoryObj<typeof meta>;

export const WithMessage: Story = {
  args: { error: { message: "Failed to load canvas (500)" } },
};

export const WithoutMessage: Story = {
  args: { error: null },
};
