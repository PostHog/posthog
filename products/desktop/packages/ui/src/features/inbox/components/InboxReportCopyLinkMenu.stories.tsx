import { LinkIcon } from "@phosphor-icons/react";
import { Button } from "@posthog/quill";
import { InboxReportCopyLinkMenu } from "@posthog/ui/features/inbox/components/InboxReportCopyLinkMenu";
import { inboxStoryReport } from "@posthog/ui/features/inbox/components/inboxStoryFixtures";
import type { Meta, StoryObj } from "@storybook/react-vite";
import { within } from "storybook/test";

const meta: Meta<typeof InboxReportCopyLinkMenu> = {
  title: "Inbox/Reports/Copy link menu",
  component: InboxReportCopyLinkMenu,
  args: {
    report: inboxStoryReport(),
    trigger: (
      <Button type="button" variant="outline" size="sm">
        <LinkIcon size={12} />
        Copy link
      </Button>
    ),
  },
};

export default meta;
type Story = StoryObj<typeof InboxReportCopyLinkMenu>;

export const Closed: Story = {};

export const Open: Story = {
  play: async ({ canvas, canvasElement, userEvent }): Promise<void> => {
    await userEvent.click(canvas.getByRole("button", { name: "Copy link" }));
    const body = within(canvasElement.ownerDocument.body);
    await body.findByText("Copy desktop link");
  },
};
