import type { Meta, StoryObj } from "@storybook/react-vite";
import { InboxDetailSkeleton } from "./InboxDetailSkeleton";

const meta: Meta<typeof InboxDetailSkeleton> = {
  title: "Inbox/InboxDetailSkeleton",
  component: InboxDetailSkeleton,
};
export default meta;

export const Default: StoryObj<typeof InboxDetailSkeleton> = {};
