import type { Task } from "@posthog/shared/domain-types";
import {
  ANONYMOUS_AUTH_STATE,
  useAuthStore,
} from "@posthog/ui/features/auth/store";
import { authKeys } from "@posthog/ui/features/auth/useCurrentUser";
import type { Meta, StoryObj } from "@storybook/react-vite";
import { useQueryClient } from "@tanstack/react-query";
import type { ReactNode } from "react";
import { taskFeedResultsQueryKey } from "../hooks/useTaskFeedResults";
import type { TaskFeed } from "../stores/taskFeedsStore";
import { TaskFeedModal } from "./TaskFeedModal";

const FEED: TaskFeed = {
  id: "feed-1",
  projectId: 1,
  ownerId: "user-1",
  name: "Billing work",
  query: "billing -status:failed pr:any",
  createdAt: "2026-07-01T08:00:00Z",
};

function task(id: string, title: string): Task {
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
  };
}

// The query never runs in a story (no authenticated client), so the match
// count comes from the cache the preview hook reads through.
function SeedResults({
  query,
  tasks,
  children,
}: {
  query: string;
  tasks: Task[];
  children: ReactNode;
}) {
  const queryClient = useQueryClient();
  queryClient.setQueryData(taskFeedResultsQueryKey(query), {
    tasks,
    isComplete: true,
  });
  return <>{children}</>;
}

const meta: Meta<typeof TaskFeedModal> = {
  title: "Spaces/TaskFeedModal",
  component: TaskFeedModal,
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
      return <Story />;
    },
  ],
  args: { open: true, onOpenChange: () => {} },
};

export default meta;
type Story = StoryObj<typeof TaskFeedModal>;

export const Create: Story = {};

export const Edit: Story = {
  args: { feed: FEED },
  decorators: [
    (Story) => (
      <SeedResults
        query={FEED.query}
        tasks={[
          task("t1", "Fix billing address validation"),
          task("t2", "Add billing period picker to invoices"),
        ]}
      >
        <Story />
      </SeedResults>
    ),
  ],
};
