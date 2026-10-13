import type { CostChecklistItem } from "@posthog/core/billing/costChecklist";
import { CostChecklistPanel } from "@posthog/ui/features/cost-management/CostChecklistPanel";
import type { Meta, StoryObj } from "@storybook/react";

const meta: Meta<typeof CostChecklistPanel> = {
  title: "Cost management/CostChecklistPanel",
  component: CostChecklistPanel,
  args: {
    onSwitchModel: () => {},
    onCreateImage: () => {},
    onSte100Toggle: () => {},
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
const ste100: CostChecklistItem = { kind: "ste100", done: false };

export const BothActive: StoryObj<typeof CostChecklistPanel> = {
  args: { items: [modelNotch, customImage, ste100] },
};

export const OneDone: StoryObj<typeof CostChecklistPanel> = {
  args: {
    items: [
      customImage,
      ste100,
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
      ste100,
      {
        kind: "install-skill",
        done: false,
        skillId: "ponytail",
        name: "Ponytail",
      },
    ],
  },
};
