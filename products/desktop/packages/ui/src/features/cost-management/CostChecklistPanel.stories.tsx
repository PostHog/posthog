import type { CostChecklistItem } from "@posthog/core/billing/costChecklist";
import { CostChecklistPanel } from "@posthog/ui/features/cost-management/CostChecklistPanel";
import type { Meta, StoryObj } from "@storybook/react";

const meta: Meta<typeof CostChecklistPanel> = {
  title: "Cost management/CostChecklistPanel",
  component: CostChecklistPanel,
  args: {
    onSwitchModel: () => {},
    onCreateImage: () => {},
    onInstallSkill: () => {},
    onUninstallSkill: () => {},
    onOpenSkill: () => {},
    busySkillIds: new Set(),
  },
  decorators: [
    (Story) => (
      <div className="max-w-3xl p-6">
        <Story />
      </div>
    ),
  ],
};

export default meta;

const modelNotch: CostChecklistItem = {
  kind: "model-notch",
  done: false,
  fromModelId: "claude-opus-5",
  toModelId: "claude-sonnet-5",
};

const customImage: CostChecklistItem = { kind: "custom-image", done: false };

export const BothActive: StoryObj<typeof CostChecklistPanel> = {
  args: { items: [modelNotch, customImage] },
};

export const OneDone: StoryObj<typeof CostChecklistPanel> = {
  args: {
    items: [
      customImage,
      { kind: "model-notch", done: true, modelId: "claude-sonnet-5" },
    ],
  },
};

export const AllDone: StoryObj<typeof CostChecklistPanel> = {
  args: {
    items: [
      { kind: "model-notch", done: true, modelId: "claude-sonnet-5" },
      { kind: "custom-image", done: true },
    ],
  },
};

export const NothingToChange: StoryObj<typeof CostChecklistPanel> = {
  args: { items: [] },
};

export const SkillItems: StoryObj<typeof CostChecklistPanel> = {
  args: {
    items: [
      {
        kind: "install-skill",
        done: false,
        skillId: "ponytail",
        name: "Ponytail",
      },
    ],
  },
};

export const EverySuggestion: StoryObj<typeof CostChecklistPanel> = {
  args: {
    items: [
      modelNotch,
      customImage,
      {
        kind: "install-skill",
        done: false,
        skillId: "ponytail",
        name: "Ponytail",
      },
    ],
  },
};
