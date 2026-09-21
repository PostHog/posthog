import type { Task, TaskRun, UserBasic } from "@posthog/shared/domain-types";
import type { Meta, StoryObj } from "@storybook/react-vite";
import { ChannelFeedView } from "./ChannelFeedView";

const adam: UserBasic = {
  id: 1,
  uuid: "user-adam",
  email: "adam@example.com",
  first_name: "Adam",
  last_name: "Bowker",
};
const marta: UserBasic = {
  id: 2,
  uuid: "user-marta",
  email: "marta@example.com",
  first_name: "Marta",
  last_name: "Nowak",
};

function run(overrides: Partial<TaskRun>): TaskRun {
  return {
    id: "run-1",
    task: "task-1",
    team: 1,
    branch: null,
    status: "completed",
    environment: "cloud",
    log_url: "",
    error_message: null,
    output: null,
    state: {},
    created_at: "2026-07-01T09:00:00Z",
    updated_at: "2026-07-01T09:05:00Z",
    completed_at: null,
    ...overrides,
  };
}

function task(overrides: Partial<Task>): Task {
  return {
    id: "task-1",
    task_number: 1,
    slug: "task-1",
    title: "Add feedback modal to spaces view",
    description:
      "Add a feedback modal to the spaces view so people can share thoughts without leaving the feed",
    created_at: "2026-07-01T09:00:00Z",
    updated_at: "2026-07-01T09:05:00Z",
    origin_product: "user_created",
    created_by: adam,
    repository: "example-org/webapp",
    ...overrides,
  };
}

// Dates sit around the frozen test-runner clock (2026-07-01T10:30Z) so the
// day separators read Today / Yesterday and the relative times stay stable.
const tasks: Task[] = [
  task({
    id: "task-pr",
    title: "Fix flaky onboarding e2e test",
    description:
      "The onboarding e2e test fails one run in five — find why and fix it",
    created_at: "2026-07-01T10:00:00Z",
    updated_at: "2026-07-01T10:20:00Z",
    latest_run: run({
      id: "run-pr",
      task: "task-pr",
      status: "completed",
      output: { pr_url: "https://github.com/example-org/webapp/pull/421" },
    }),
  }),
  task({
    id: "task-running",
    title: "Investigate signup drop-off",
    description:
      "Investigate the signup drop-off we saw over the weekend. Check the funnel between the pricing page and the signup form, and look at whether the new consent banner overlaps the submit button on small screens.",
    created_at: "2026-07-01T09:15:00Z",
    updated_at: "2026-07-01T09:40:00Z",
    created_by: marta,
    latest_run: run({
      id: "run-running",
      task: "task-running",
      status: "in_progress",
    }),
  }),
  task({
    id: "task-multi-pr",
    title: "Split the settings page into sections",
    description: "Split the settings page into sections with one PR each",
    created_at: "2026-06-30T16:00:00Z",
    updated_at: "2026-06-30T18:00:00Z",
    latest_run: run({
      id: "run-multi",
      task: "task-multi-pr",
      status: "completed",
      output: {
        pr_urls: [
          "https://github.com/example-org/webapp/pull/415",
          "https://github.com/example-org/webapp/pull/416",
          "https://github.com/example-org/webapp/pull/417",
        ],
      },
    }),
  }),
  task({
    id: "task-other-repo",
    title: "Bump the SDK to the latest release",
    description: "Bump the SDK to the latest release and fix the type breaks",
    created_at: "2026-06-30T11:00:00Z",
    updated_at: "2026-06-30T11:30:00Z",
    repository: "example-org/sdk",
    created_by: marta,
    latest_run: run({
      id: "run-failed",
      task: "task-other-repo",
      status: "failed",
    }),
  }),
  task({
    id: "task-old",
    title: "Summarize last week's shipped changes",
    description: "Summarize last week's shipped changes for the changelog",
    created_at: "2026-06-24T12:00:00Z",
    updated_at: "2026-06-24T12:10:00Z",
    created_by: null,
    origin_product: "slack",
  }),
];

const systemMessages = [
  {
    id: "system-context",
    createdAt: "2026-06-30T10:59:59Z",
    text: "Building CONTEXT.md for this channel",
  },
];

function MockComposer() {
  return (
    <div className="rounded-xl border border-(--gray-6) bg-(--gray-2) px-4 py-3 text-(--gray-9) text-sm">
      Start a new task…
    </div>
  );
}

const meta: Meta<typeof ChannelFeedView> = {
  title: "Spaces/ChannelFeedView",
  component: ChannelFeedView,
  parameters: { layout: "fullscreen" },
  decorators: [
    (Story) => (
      <div className="flex h-[720px] flex-col">
        <Story />
      </div>
    ),
  ],
  args: {
    channelId: "channel-1",
    isLoading: false,
    onOpenTask: () => undefined,
    onOpenThread: () => undefined,
  },
};

export default meta;
type Story = StoryObj<typeof ChannelFeedView>;

export const Feed: Story = {
  args: {
    tasks,
    systemMessages,
    composer: <MockComposer />,
  },
};

export const PendingKickoff: Story = {
  args: {
    tasks: tasks.slice(1),
    composer: <MockComposer />,
    pending: [
      {
        id: "pending-1",
        prompt: "Add a dark-mode toggle to the settings page",
      },
    ],
  },
};

export const Loading: Story = {
  args: {
    tasks: [],
    isLoading: true,
    composer: <MockComposer />,
  },
};

export const EmptyChannel: Story = {
  args: {
    tasks: [],
    composer: <MockComposer />,
    emptyState: (
      <div className="mx-auto w-full max-w-[660px] py-10 text-center text-(--gray-9) text-sm">
        No tasks yet. Start one above.
      </div>
    ),
  },
};
