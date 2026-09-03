import {
  InboxLoadFailure,
  InboxStaleListNotice,
} from "@posthog/ui/features/inbox/components/InboxLoadFailure";
import type { Meta, StoryObj } from "@storybook/react-vite";

const meta: Meta<typeof InboxLoadFailure> = {
  title: "Inbox/Reports/Load failure",
  component: InboxLoadFailure,
  decorators: [
    (Story) => (
      <div className="mx-auto flex w-full max-w-4xl flex-col gap-4 px-6 py-4">
        <Story />
      </div>
    ),
  ],
  args: {
    noun: "reports",
    onRetry: () => Promise.resolve(),
  },
};

export default meta;
type Story = StoryObj<typeof InboxLoadFailure>;

export const NothingLoaded: Story = {};

export const StaleList: Story = {
  render: (args) => <InboxStaleListNotice {...args} />,
};
