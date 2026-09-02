import type { ArchivedTask } from "@posthog/shared";
import type { Task } from "@posthog/shared/domain-types";
import {
  ArchivedTasksViewPresentation,
  type ArchivedTaskWithDetails,
} from "@posthog/ui/features/archive/ArchivedTasksView";
import { Box } from "@radix-ui/themes";
import type { Meta, StoryObj } from "@storybook/react-vite";

const STORY_NOW = Date.parse("2026-07-01T10:30:00Z");
const DAY_IN_MS = 86_400_000;

function createArchivedTask(id: string, daysAgo: number): ArchivedTask {
  return {
    taskId: id,
    archivedAt: new Date(STORY_NOW - daysAgo * DAY_IN_MS).toISOString(),
    folderId: "folder-1",
    mode: "worktree",
    worktreeName: "feature-wt",
    branchName: `feature/branch-${id}`,
    checkpointId: "checkpoint-123",
  };
}

function createTask(
  id: string,
  title: string,
  daysAgo: number,
  repo: string,
): Task {
  const now = new Date(STORY_NOW - daysAgo * DAY_IN_MS).toISOString();
  return {
    id,
    task_number: null,
    slug: id,
    title,
    description: "",
    created_at: now,
    updated_at: now,
    origin_product: "twig",
    repository: `org/${repo}`,
  };
}

function createItem(
  id: string,
  title: string,
  daysAgo: number,
  repo: string,
): ArchivedTaskWithDetails {
  return {
    archived: createArchivedTask(id, daysAgo),
    task: createTask(id, title, daysAgo, repo),
  };
}

const sampleItems: ArchivedTaskWithDetails[] = [
  createItem("task-1", "Add dark mode support", 1, "frontend"),
  createItem("task-2", "Fix login redirect bug", 2, "backend"),
  createItem("task-3", "Refactor database queries", 7, "api-server"),
  createItem("task-4", "Update dependencies", 14, "monorepo"),
];

const meta: Meta<typeof ArchivedTasksViewPresentation> = {
  title: "Archive/ArchivedTasksView",
  component: ArchivedTasksViewPresentation,
  parameters: { layout: "fullscreen" },
  decorators: [
    (Story) => (
      <Box className="h-screen w-full">
        <Story />
      </Box>
    ),
  ],
  args: {
    items: sampleItems,
    isLoading: false,
    branchNotFound: null,
    onUnarchive: () => {},
    onDelete: (_taskId: string) => {},
    onContextMenu: () => {},
    onBranchNotFoundClose: () => {},
    onRecreateBranch: () => {},
  },
};

export default meta;
type Story = StoryObj<typeof ArchivedTasksViewPresentation>;

export const Default: Story = {};

export const Loading: Story = {
  args: { items: [], isLoading: true },
};

export const Empty: Story = {
  args: { items: [] },
};

export const BranchNotFoundDialog: Story = {
  args: {
    branchNotFound: { taskId: "task-1", branchName: "feature/dark-mode" },
  },
};

export const SingleTask: Story = {
  args: { items: [sampleItems[0]] },
};

export const ManyTasks: Story = {
  args: {
    items: [
      ...sampleItems,
      createItem("task-5", "Implement caching layer", 30, "cache"),
      createItem("task-6", "Add unit tests", 45, "testing"),
      createItem("task-7", "Setup CI/CD pipeline", 60, "devops"),
      createItem("task-8", "Migrate to TypeScript 5.0", 90, "core"),
    ],
  },
};

export const WithMissingTask: Story = {
  args: {
    items: [
      ...sampleItems,
      {
        archived: createArchivedTask("task-missing", 5),
        task: null,
      },
    ],
  },
};

export const LongLabels: Story = {
  args: {
    items: [
      createItem(
        "task-long-1",
        "This is an extremely long task title that should demonstrate how the table handles text overflow",
        1,
        "very-long-repository-name-that-exceeds-normal-length",
      ),
      createItem(
        "task-long-2",
        "Another long title: Implement comprehensive authentication system with OAuth2 and SAML support",
        3,
        "auth-service",
      ),
      createItem("task-short", "Short", 0, "repo"),
    ],
  },
};

export const MixedModes: Story = {
  args: {
    items: [
      {
        archived: { ...createArchivedTask("t1", 1), mode: "cloud" },
        task: createTask("t1", "Cloud deploy pipeline", 10, "infra"),
      },
      {
        archived: { ...createArchivedTask("t2", 5), mode: "local" },
        task: createTask("t2", "Local debugging session", 3, "frontend"),
      },
      {
        archived: { ...createArchivedTask("t3", 0), mode: "worktree" },
        task: createTask("t3", "Worktree refactor", 20, "backend"),
      },
    ],
  },
};
