import type { Meta, StoryObj } from "@storybook/react-vite";
import { SpaceSetupRetryDialog } from "./SpaceSetupRetryDialog";

const meta = {
  title: "Spaces/SpaceSetupRetryDialog",
  component: SpaceSetupRetryDialog,
  args: {
    open: true,
    onOpenChange: () => {},
    error: "Setup is unavailable. Try again.",
    busy: false,
    onRetry: () => {},
    onOpenSpace: () => {},
  },
} satisfies Meta<typeof SpaceSetupRetryDialog>;

export default meta;
type Story = StoryObj<typeof meta>;

export const Failed: Story = {};
export const Retrying: Story = { args: { busy: true } };
