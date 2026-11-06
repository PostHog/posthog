import { LEAN_SKILLS } from "@posthog/core/billing/leanSkills";
import { LeanSkillDialog } from "@posthog/ui/features/cost-management/LeanSkillDialog";
import type { Meta, StoryObj } from "@storybook/react";

const meta: Meta<typeof LeanSkillDialog> = {
  title: "Cost management/LeanSkillDialog",
  component: LeanSkillDialog,
  args: {
    skill: LEAN_SKILLS[0],
    installed: false,
    busy: false,
    onInstall: () => {},
    onUninstall: () => {},
    onClose: () => {},
  },
};

export default meta;

export const Measured: StoryObj<typeof LeanSkillDialog> = {};

export const Installed: StoryObj<typeof LeanSkillDialog> = {
  args: { installed: true },
};

export const NoTrial: StoryObj<typeof LeanSkillDialog> = {
  args: { skill: LEAN_SKILLS[1] },
};
