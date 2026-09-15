import type { Meta, StoryObj } from "@storybook/react-vite";
import { BillingSwitchQueuedDialog } from "./BillingSwitchQueuedDialog";

const meta: Meta<typeof BillingSwitchQueuedDialog> = {
  title: "Sessions/BillingSwitchQueuedDialog",
  component: BillingSwitchQueuedDialog,
  args: {
    open: true,
    queuedCount: 3,
    onConfirm: () => {},
    onCancel: () => {},
  },
};

export default meta;
type Story = StoryObj<typeof BillingSwitchQueuedDialog>;

export const SeveralQueued: Story = {};

export const OneQueued: Story = {
  args: {
    queuedCount: 1,
  },
};
