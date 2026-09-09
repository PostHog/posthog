import { inboxStoryReport } from "@posthog/ui/features/inbox/components/inboxStoryFixtures";
import type { Meta, StoryObj } from "@storybook/react-vite";
import { ReportVerdictBanner } from "./ReportVerdictBanner";

const meta: Meta<typeof ReportVerdictBanner> = {
  title: "Inbox/Reports/Report verdict",
  component: ReportVerdictBanner,
  parameters: { layout: "padded" },
  args: {
    report: inboxStoryReport({ status: "potential" }),
  },
};

export default meta;
type Story = StoryObj<typeof ReportVerdictBanner>;

export const WaitingForSignals: Story = {};

export const DismissedAsAlreadyFixed: Story = {
  args: {
    report: inboxStoryReport({
      status: "potential",
      dismissal_reason: "already_fixed",
    }),
  },
};

export const Queued: Story = {
  args: { report: inboxStoryReport({ status: "candidate" }) },
};

export const Investigating: Story = {
  args: { report: inboxStoryReport({ status: "in_progress" }) },
};
