import type { Meta, StoryObj } from "@storybook/react-vite";
import { UnpublishedDreamNotice } from "./UnpublishedDreamNotice";

const meta = {
  title: "Features/Context wiki/Unpublished dream",
  component: UnpublishedDreamNotice,
  decorators: [
    (Story) => (
      <div className="w-72 max-w-full">
        <Story />
      </div>
    ),
  ],
  args: {
    run: {
      task_url: "https://example.com/project/123/tasks/dream-task",
      run_status: "completed",
      started_at: "2026-09-01T03:00:00Z",
    },
  },
} satisfies Meta<typeof UnpublishedDreamNotice>;

export default meta;
type Story = StoryObj<typeof meta>;

export const NoUpdate: Story = {};
export const Failed: Story = {
  args: { run: { ...meta.args.run, run_status: "failed" } },
};
export const Canceled: Story = {
  args: { run: { ...meta.args.run, run_status: "cancelled" } },
};
