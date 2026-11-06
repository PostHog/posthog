import type { Meta, StoryObj } from "@storybook/react-vite";
import { ModelSwitchCacheDialog } from "./ModelSwitchCacheDialog";

const meta: Meta<typeof ModelSwitchCacheDialog> = {
  title: "Sessions/ModelSwitchCacheDialog",
  component: ModelSwitchCacheDialog,
  args: {
    open: true,
    fromModelLabel: "Claude Opus 5",
    toModelId: "claude-haiku-4-5",
    toModelLabel: "Claude Haiku 4.5",
    contextTokens: 84_000,
    onConfirm: async () => {},
    onCancel: () => {},
  },
};

export default meta;
type Story = StoryObj<typeof ModelSwitchCacheDialog>;

export const SwitchToCheaper: Story = {};

export const SwitchToPricier: Story = {
  args: {
    fromModelLabel: "Claude Sonnet 5",
    toModelId: "claude-fable-5",
    toModelLabel: "Claude Fable 5",
  },
};

export const UnknownPricing: Story = {
  args: {
    fromModelLabel: "Custom model A",
    toModelId: "custom-model-b",
    toModelLabel: "Custom model B",
  },
};

export const WithoutCostEstimate: Story = {
  args: {
    contextTokens: undefined,
  },
};
