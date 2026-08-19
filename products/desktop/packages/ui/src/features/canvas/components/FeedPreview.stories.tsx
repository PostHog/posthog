import { PencilSimpleIcon, TrashIcon } from "@phosphor-icons/react";
import { Card } from "@posthog/quill";
import type { Task, TaskRun } from "@posthog/shared/domain-types";
import type { Meta, StoryObj } from "@storybook/react-vite";
import type { TaskFeed } from "../stores/taskFeedsStore";
import type { ChannelActionItem } from "./channelActions";
import { FeedPreviewContent } from "./FeedPreview";

const FEED: TaskFeed = {
  id: "feed-1",
  name: "Billing work",
  query: "billing created-by:@me -status:failed",
  createdAt: "2026-07-01T08:00:00Z",
};

const ACTIONS: ChannelActionItem[] = [
  {
    key: "edit",
    label: "Edit feed",
    icon: <PencilSimpleIcon size={14} />,
    onSelect: () => {},
  },
  {
    key: "delete",
    label: "Delete feed",
    icon: <TrashIcon size={14} />,
    variant: "destructive",
    separatorBefore: true,
    onSelect: () => {},
  },
];

function run(status: TaskRun["status"]): TaskRun {
  return {
    id: `run-${status}`,
    task: "task-1",
    team: 1,
    branch: null,
    status,
    environment: "cloud",
    log_url: "",
    error_message: null,
    output: null,
    state: {},
    created_at: "2026-07-01T09:00:00Z",
    updated_at: "2026-07-01T09:05:00Z",
    completed_at: null,
  };
}

function task(id: string, title: string, status: TaskRun["status"]): Task {
  return {
    id,
    task_number: 1,
    slug: id,
    title,
    description: title,
    created_at: "2026-07-01T09:00:00Z",
    updated_at: "2026-07-01T09:05:00Z",
    origin_product: "user_created",
    repository: "example-org/webapp",
    latest_run: run(status),
  };
}

const TASKS: Task[] = [
  task("t1", "Fix billing address validation", "in_progress"),
  task("t2", "Add billing period picker to invoices", "completed"),
  task("t3", "Reconcile invoice line items", "queued"),
];

const meta: Meta<typeof FeedPreviewContent> = {
  title: "Spaces/FeedPreview",
  component: FeedPreviewContent,
  // The same shell the sidebar's shared hover card wraps every payload in.
  decorators: [
    (Story) => (
      <Card
        size="sm"
        className="w-72 gap-0 border border-border py-0 shadow-md"
      >
        <Story />
      </Card>
    ),
  ],
  args: {
    payload: { feed: FEED, actions: ACTIONS },
    onAction: () => {},
  },
};

export default meta;
type Story = StoryObj<typeof FeedPreviewContent>;

export const WithMatches: Story = {
  args: { tasks: TASKS, total: TASKS.length },
};

export const Empty: Story = {
  args: { tasks: [], total: 0 },
};

export const Loading: Story = {
  args: { tasks: [], total: null },
};
