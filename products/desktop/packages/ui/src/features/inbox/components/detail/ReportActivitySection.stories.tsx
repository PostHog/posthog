import type { Meta, StoryObj } from "@storybook/react-vite";
import { ReportActivitySection } from "./ReportActivitySection";

const meta: Meta<typeof ReportActivitySection> = {
  title: "Inbox/Reports/Activity confirmations",
  component: ReportActivitySection,
  parameters: { layout: "padded" },
  args: { reportId: "example-report", collapsedNoteCount: 3 },
  play: async ({ canvas, userEvent }): Promise<void> => {
    await userEvent.click(canvas.getByText("Activity"));
  },
};

export default meta;
type Story = StoryObj<typeof ReportActivitySection>;

export const SeveralConfirmations: Story = {};
export const OneConfirmation: Story = { args: { collapsedNoteCount: 1 } };
