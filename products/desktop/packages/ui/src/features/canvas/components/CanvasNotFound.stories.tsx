import type { Meta, StoryObj } from "@storybook/react-vite";
import { CanvasNotFoundView } from "./CanvasNotFound";

const meta = {
  title: "Canvas/CanvasNotFound",
  component: CanvasNotFoundView,
  parameters: { layout: "fullscreen" },
  args: { projectName: "Marketing" },
  decorators: [
    (Story) => (
      <div className="h-100">
        <Story />
      </div>
    ),
  ],
} satisfies Meta<typeof CanvasNotFoundView>;

export default meta;
type Story = StoryObj<typeof meta>;

export const NoAccessOrOtherProject: Story = {
  args: { channel: undefined },
};

export const DeletedFromVisibleChannel: Story = {
  args: { channel: { id: "chan-1", name: "Growth" } },
};
