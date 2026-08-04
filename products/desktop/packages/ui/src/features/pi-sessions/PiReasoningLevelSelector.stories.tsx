import type {
  PiModelSelection,
  PiThinkingLevel,
} from "@posthog/core/pi-runtime/piSessionController";
import type { Meta, StoryObj } from "@storybook/react-vite";
import { PiReasoningLevelSelector } from "./PiReasoningLevelSelector";

const haiku: PiModelSelection = { provider: "posthog", id: "claude-haiku-4-5" };
const sonnet: PiModelSelection = { provider: "posthog", id: "claude-sonnet-5" };
const opus: PiModelSelection = { provider: "posthog", id: "claude-opus-5" };
const thinkingLevels: PiThinkingLevel[] = [
  "off",
  "minimal",
  "low",
  "medium",
  "high",
];

const meta: Meta<typeof PiReasoningLevelSelector> = {
  title: "Pi Sessions/PiReasoningLevelSelector",
  component: PiReasoningLevelSelector,
  args: {
    models: [haiku, sonnet, opus],
    currentModel: haiku,
    thinkingLevels,
    currentThinkingLevel: "high",
    onModelChange: () => {},
    onThinkingLevelChange: () => {},
  },
  decorators: [
    (Story) => (
      <div className="p-8">
        <Story />
      </div>
    ),
  ],
};

export default meta;
type Story = StoryObj<typeof PiReasoningLevelSelector>;

export const Default: Story = {};

export const WithoutThinkingSupport: Story = {
  args: {
    thinkingLevels: ["off"],
    currentThinkingLevel: "off",
  },
};

export const ModelMissingFromCatalog: Story = {
  args: {
    currentModel: { provider: "posthog", id: "claude-legacy" },
  },
};

export const Loading: Story = {
  args: {
    models: [],
    currentModel: undefined,
    thinkingLevels: [],
    currentThinkingLevel: undefined,
    isLoading: true,
  },
};
