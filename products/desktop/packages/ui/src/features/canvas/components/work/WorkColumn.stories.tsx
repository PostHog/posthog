import type { Task, TaskChannel } from "@posthog/shared/domain-types";
import { TASK_CHANNELS_QUERY_KEY } from "@posthog/ui/features/canvas/hooks/useTaskChannels";
import { taskKeys } from "@posthog/ui/features/tasks/taskKeys";
import type { Meta, StoryObj } from "@storybook/react-vite";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { WorkColumn } from "./WorkColumn";

const ME_ID = 1;
const HOUR = 60 * 60 * 1000;

function task(index: number, title: string, hoursAgo: number): Task {
  const at = new Date(Date.UTC(2026, 6, 1, 10, 30) - hoursAgo * HOUR);
  return {
    id: `task-${index}`,
    task_number: index,
    slug: `task-${index}`,
    title,
    description: "",
    created_at: at.toISOString(),
    updated_at: at.toISOString(),
    last_activity_at: at.toISOString(),
    origin_product: "user_created",
    channel: "channel-personal",
    created_by: { id: ME_ID, uuid: "me-uuid", first_name: "Sam", email: null },
  };
}

const TASK_TITLES = [
  "Trim the empty state on the endpoints list",
  "Cache the repository picker between opens",
  "Drop the duplicate poll on the activity feed",
  "Make the filter menu remember its last sort",
  "Handle a missing avatar on a mention row",
  "Split the oversized settings module",
  "Add a retry to the flaky upload test",
  "Rename the branch column in the runs table",
  "Fix the caret alignment in the sidebar tree",
  "Stop the toast from covering the composer",
  "Measure how long a cold start takes",
  "Move the copy button beside the title",
  "Guard the submit button against a double click",
  "Truncate long space names in the picker",
];

const TASKS: Task[] = TASK_TITLES.map((title, index) =>
  task(index + 1, title, index * 3),
);

function channel(
  name: string,
  overrides: Partial<TaskChannel> = {},
): TaskChannel {
  return {
    id: `channel-${name}`,
    name,
    channel_type: "public",
    starred: true,
    created_at: "2026-06-01T00:00:00Z",
    ...overrides,
  };
}

const CHANNELS: TaskChannel[] = [
  channel("me", { channel_type: "personal", system_role: "personal" }),
  channel("desktop-canvas"),
  channel("desktop-cost-management"),
  channel("desktop-multiplayer"),
  channel("desktop-subscriptions"),
  channel("growth-experiments"),
  channel("ingestion-pipeline"),
  channel("replay-vision"),
  channel("support-triage"),
  channel("web-analytics"),
];

/**
 * The column reads its rows through authenticated queries that never resolve in
 * Storybook, so seed their caches — a disabled query still serves cached data.
 */
function seededClient(): QueryClient {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  client.setQueryData(["me"], { id: ME_ID, uuid: "me-uuid" });
  client.setQueryData(TASK_CHANNELS_QUERY_KEY, CHANNELS);
  client.setQueryData(taskKeys.list({ createdBy: ME_ID }), TASKS);
  return client;
}

const meta = {
  title: "Canvas/WorkColumn",
  component: WorkColumn,
  parameters: { layout: "fullscreen" },
  decorators: [
    (Story) => (
      <QueryClientProvider client={seededClient()}>
        <div className="h-screen w-[280px] border-border border-r">
          <Story />
        </div>
      </QueryClientProvider>
    ),
  ],
} satisfies Meta<typeof WorkColumn>;

export default meta;
type Story = StoryObj<typeof meta>;

/** Recent capped at five rows, spaces below it. */
export const Default: Story = {};
