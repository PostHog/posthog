import type { Task, TaskRun, UserBasic } from "@posthog/shared/domain-types";
import {
  ANONYMOUS_AUTH_STATE,
  useAuthStore,
} from "@posthog/ui/features/auth/store";
import { authKeys } from "@posthog/ui/features/auth/useCurrentUser";
import type { Meta, StoryObj } from "@storybook/react-vite";
import { useQueryClient } from "@tanstack/react-query";
import type { ReactNode } from "react";
import { taskFeedResultsQueryKey } from "../hooks/useTaskFeedResults";
import { type TaskFeed, useTaskFeedsStore } from "../stores/taskFeedsStore";
import { TaskFeedHome } from "./TaskFeedHome";

const adam: UserBasic = {
  id: 1,
  uuid: "user-adam",
  email: "adam@example.com",
  first_name: "Adam",
  last_name: "Bowker",
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
    title: "Reconcile invoice line items",
    description:
      "Reconcile invoice line items against the ledger and flag mismatches",
    created_at: "2026-07-01T09:00:00Z",
    updated_at: "2026-07-01T09:05:00Z",
    origin_product: "user_created",
    created_by: adam,
    repository: "example-org/webapp",
    ...overrides,
  };
}

const FEED: TaskFeed = {
  id: "feed-1",
  projectId: 1,
  ownerId: "user-1",
  name: "Billing work",
  query: "billing -status:failed pr:any",
  createdAt: "2026-07-01T08:00:00Z",
};

// Dates sit around the frozen test-runner clock (2026-07-01T10:30Z) so the
// day separators read Today and the relative times stay stable.
const results: Task[] = [
  task({
    id: "task-billing-1",
    title: "Fix billing address validation",
    description: "Billing address validation rejects valid postcodes",
    created_at: "2026-07-01T10:00:00Z",
    updated_at: "2026-07-01T10:20:00Z",
    latest_run: run({
      id: "run-b1",
      task: "task-billing-1",
      status: "in_progress",
      output: { pr_url: "https://github.com/example-org/webapp/pull/62" },
    }),
  }),
  task({
    id: "task-billing-2",
    title: "Add billing period picker to invoices",
    created_at: "2026-07-01T09:30:00Z",
    updated_at: "2026-07-01T09:45:00Z",
    latest_run: run({
      id: "run-b2",
      task: "task-billing-2",
      output: { pr_url: "https://github.com/example-org/webapp/pull/58" },
    }),
  }),
];

// The feed's query never runs in a story (no authenticated client), so the
// results come from the cache the hook reads through.
function SeedResults({
  tasks,
  children,
}: {
  tasks: Task[];
  children: ReactNode;
}) {
  const queryClient = useQueryClient();
  queryClient.setQueryData(taskFeedResultsQueryKey(FEED.query), {
    tasks,
    isComplete: true,
  });
  return <>{children}</>;
}

const meta: Meta<typeof TaskFeedHome> = {
  title: "Spaces/TaskFeedHome",
  component: TaskFeedHome,
  parameters: { layout: "fullscreen" },
  decorators: [
    (Story) => {
      const queryClient = useQueryClient();
      queryClient.setQueryData(authKeys.currentUser(null), { uuid: "user-1" });
      useAuthStore.setState({
        authState: {
          ...ANONYMOUS_AUTH_STATE,
          currentProjectId: FEED.projectId,
        },
      });
      useTaskFeedsStore.setState({ feeds: [FEED] });
      return (
        <div className="flex h-[720px] flex-col">
          <Story />
        </div>
      );
    },
  ],
  args: { feedId: FEED.id },
};

export default meta;
type Story = StoryObj<typeof TaskFeedHome>;

export const WithResults: Story = {
  decorators: [
    (Story) => (
      <SeedResults tasks={results}>
        <Story />
      </SeedResults>
    ),
  ],
};

export const Empty: Story = {
  decorators: [
    (Story) => (
      <SeedResults tasks={[]}>
        <Story />
      </SeedResults>
    ),
  ],
};

export const NotFound: Story = {
  args: { feedId: "feed-missing" },
};
