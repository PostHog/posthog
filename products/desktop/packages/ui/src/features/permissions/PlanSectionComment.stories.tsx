import type { Meta, StoryObj } from "@storybook/react-vite";
import { PlanSectionComment } from "./PlanSectionComment";

const meta: Meta<typeof PlanSectionComment> = {
  title: "Components/Permissions/PlanSectionComment",
  component: PlanSectionComment,
  parameters: { layout: "padded" },
  args: {
    onSubmit: () => undefined,
    onDismiss: () => undefined,
  },
};

export default meta;
type Story = StoryObj<typeof PlanSectionComment>;

export const Empty: Story = {};

export const Editing: Story = {
  args: { initialText: "Keep this step compatible with the existing API." },
};
