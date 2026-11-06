import type { Meta, StoryObj } from "@storybook/react-vite";
import { fn } from "storybook/test";
import { CanvasAgentRequestDialog } from "./CanvasAgentRequestDialog";

const meta = {
  title: "Canvas/CanvasAgentRequestDialog",
  component: CanvasAgentRequestDialog,
  args: {
    prompt: "Summarize the retro board and add the themes below the cards.",
    loading: false,
    onCancel: fn(),
    onConfirm: fn(),
  },
} satisfies Meta<typeof CanvasAgentRequestDialog>;

export default meta;
type Story = StoryObj<typeof meta>;

export const Default: Story = {};

export const StartingRun: Story = {
  args: { loading: true },
};
