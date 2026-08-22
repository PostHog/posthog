import { CustomImageWizard } from "@posthog/ui/features/cost-management/CustomImageWizard";
import type { Meta, StoryObj } from "@storybook/react";

const meta: Meta<typeof CustomImageWizard> = {
  title: "Cost management/CustomImageWizard",
  component: CustomImageWizard,
  args: {
    open: true,
    defaultRepository: "posthog/posthog",
    host: "github",
    creating: false,
    onCreate: () => {},
    onCancel: () => {},
  },
};

export default meta;

export const Wizard: StoryObj<typeof CustomImageWizard> = {};

export const NoRepository: StoryObj<typeof CustomImageWizard> = {
  args: { defaultRepository: null },
};

export const Creating: StoryObj<typeof CustomImageWizard> = {
  args: { creating: true },
};
