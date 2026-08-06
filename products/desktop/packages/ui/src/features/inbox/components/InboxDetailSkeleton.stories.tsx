import type { Meta, StoryObj } from "@storybook/react-vite";
import { InboxDetailSkeleton } from "./InboxDetailSkeleton";

const meta: Meta<typeof InboxDetailSkeleton> = {
  title: "Inbox/InboxDetailSkeleton",
  component: InboxDetailSkeleton,
  parameters: {
    // The skeleton IS the loading state; the visual test runner must not wait
    // for it to disappear.
    testOptions: { waitForLoadersToDisappear: false },
  },
};
export default meta;

export const Default: StoryObj<typeof InboxDetailSkeleton> = {};
