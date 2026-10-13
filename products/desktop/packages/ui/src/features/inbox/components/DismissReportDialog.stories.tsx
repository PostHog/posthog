import { inboxStoryReport } from "@posthog/ui/features/inbox/components/inboxStoryFixtures";
import type { Meta, StoryObj } from "@storybook/react-vite";
import { DismissReportDialog } from "./DismissReportDialog";

const meta: Meta<typeof DismissReportDialog> = {
  title: "Inbox/Reports/Dismiss dialog",
  component: DismissReportDialog,
  parameters: { layout: "centered" },
  args: {
    open: true,
    report: inboxStoryReport({
      title: "fix(insights): prevent duplicate refreshes after reconnecting",
    }),
    isSubmitting: false,
    snoozeDisabledReason: null,
    initialReason: "already_fixed",
    onOpenChange: () => {},
    onConfirm: () => {},
  },
};

export default meta;
type Story = StoryObj<typeof DismissReportDialog>;

export const TemporaryDismissal: Story = {};
