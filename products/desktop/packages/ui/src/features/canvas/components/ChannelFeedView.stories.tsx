import type { Task, UserBasic } from "@posthog/shared/domain-types";
import type { Meta, StoryObj } from "@storybook/react-vite";
import { TaskFeedRow } from "./ChannelFeedView";

function MockTaskCard({ title }: { title: string }) {
  return (
    <div className="mt-1.5 rounded-sm border border-border-primary px-3 py-2.5">
      <div className="flex items-center justify-between gap-2">
        <span className="font-medium text-sm">{title}</span>
        <span className="rounded-full bg-fill-secondary px-2 py-0.5 text-muted-foreground text-xs">
          Ready
        </span>
      </div>
    </div>
  );
}

const user = (overrides: Partial<UserBasic> = {}): UserBasic => ({
  id: 1,
  uuid: "user-1",
  email: "adam@posthog.com",
  first_name: "Adam",
  last_name: "Bowker",
  ...overrides,
});

const task = (overrides: Partial<Task> = {}): Task => ({
  id: "task-1",
  task_number: 1,
  slug: "task-1",
  title: "Add feedback modal to channels view",
  description:
    "Add a feedback modal to the channels view so people can share thoughts without leaving the feed",
  created_at: "2026-07-17T12:00:00.000Z",
  updated_at: "2026-07-17T12:00:00.000Z",
  origin_product: "user_created",
  created_by: user(),
  ...overrides,
});

const meta: Meta<typeof TaskFeedRow> = {
  title: "Channels/TaskFeedRow",
  component: TaskFeedRow,
  decorators: [
    (Story) => (
      <div className="max-w-xl">
        <Story />
      </div>
    ),
  ],
};

export default meta;
type Story = StoryObj<typeof TaskFeedRow>;

export const HumanStarted: Story = {
  args: {
    task: task(),
    children: <MockTaskCard title="Add feedback modal to channels view" />,
  },
};

export const HumanEmailOnly: Story = {
  args: {
    task: task({
      created_by: user({ first_name: undefined, last_name: undefined }),
      title: "Make background color configurable",
      description: "Make the channel background color configurable in settings",
    }),
    children: <MockTaskCard title="Make background color configurable" />,
  },
};

export const AgentOrigin: Story = {
  args: {
    task: task({
      origin_product: "slack",
      title: "Investigate signup drop-off",
      description: "Investigate the signup drop-off we saw over the weekend",
    }),
    children: <MockTaskCard title="Investigate signup drop-off" />,
  },
};

export const LongPrompt: Story = {
  args: {
    task: task({
      description:
        "Rework the channel feed so each row reads as the person who started the task rather than the agent, show a preview of their prompt under the header, keep the task card below, and make sure long prompts truncate cleanly instead of pushing the card down the feed",
    }),
    children: <MockTaskCard title="Rework the channel feed attribution" />,
  },
};

export const NoPrompt: Story = {
  args: {
    task: task({ description: "", title: "Untitled task" }),
    children: <MockTaskCard title="Untitled task" />,
  },
};

export const NoStarter: Story = {
  args: {
    task: task({
      created_by: null,
      title: "Untitled task",
      description: "Summarize this week's shipped changes",
    }),
    children: <MockTaskCard title="Summarize this week's shipped changes" />,
  },
};
