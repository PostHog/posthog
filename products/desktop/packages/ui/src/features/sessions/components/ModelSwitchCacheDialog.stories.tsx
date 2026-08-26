import type { Meta, StoryObj } from "@storybook/react-vite";
import { ModelSwitchCacheDialog } from "./ModelSwitchCacheDialog";

const meta: Meta<typeof ModelSwitchCacheDialog> = {
  title: "Sessions/ModelSwitchCacheDialog",
  component: ModelSwitchCacheDialog,
  args: {
    open: true,
    fromModelId: "claude-opus-5",
    fromModelLabel: "Claude Opus 5",
    toModelId: "claude-haiku-4-5",
    toModelLabel: "Claude Haiku 4.5",
    onConfirm: () => {},
    onCancel: () => {},
  },
};

export default meta;
type Story = StoryObj<typeof ModelSwitchCacheDialog>;

export const SwitchToCheaper: Story = {};

export const SwitchToPricier: Story = {
  args: {
    fromModelId: "claude-sonnet-5",
    fromModelLabel: "Claude Sonnet 5",
    toModelId: "claude-fable-5",
    toModelLabel: "Claude Fable 5",
  },
};

export const UnknownPricing: Story = {
  args: {
    fromModelId: "custom-model-a",
    fromModelLabel: "Custom model A",
    toModelId: "custom-model-b",
    toModelLabel: "Custom model B",
  },
};
