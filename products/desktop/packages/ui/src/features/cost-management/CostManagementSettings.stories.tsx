import type { CostChecklistItem } from "@posthog/core/billing/costChecklist";
import { CostManagementView } from "@posthog/ui/features/cost-management/CostManagementView";
import type { Meta, StoryObj } from "@storybook/react";

const meta: Meta<typeof CostManagementView> = {
  title: "Cost management/CostManagementView",
  component: CostManagementView,
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
      <div className="max-w-4xl p-8">
        <Story />
      </div>
    ),
  ],
};

export default meta;

const items: CostChecklistItem[] = [
  {
    kind: "model-notch",
    done: false,
    fromModelId: "claude-opus-5",
    toModelId: "claude-sonnet-5",
  },
  { kind: "custom-image", done: false },
];

export const Page: StoryObj<typeof CostManagementView> = {
  args: { items },
};

export const EverythingChecked: StoryObj<typeof CostManagementView> = {
  args: {
    items: [
      { kind: "model-notch", done: true, modelId: "claude-sonnet-5" },
      { kind: "custom-image", done: true },
    ],
  },
};
