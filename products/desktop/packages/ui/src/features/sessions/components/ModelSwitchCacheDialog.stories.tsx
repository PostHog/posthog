import type { Meta, StoryObj } from "@storybook/react-vite";
import { ModelSwitchCacheDialog } from "./ModelSwitchCacheDialog";

const meta: Meta<typeof ModelSwitchCacheDialog> = {
  title: "Sessions/ModelSwitchCacheDialog",
  component: ModelSwitchCacheDialog,
  args: {
    open: true,
    toModelLabel: "Claude Haiku 4.5",
    onConfirm: () => {},
    onCancel: () => {},
  },
};

export default meta;
type Story = StoryObj<typeof ModelSwitchCacheDialog>;

export const Open: Story = {};
