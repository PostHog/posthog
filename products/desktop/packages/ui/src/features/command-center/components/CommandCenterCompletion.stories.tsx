import type { Task } from "@posthog/shared/domain-types";
import type { Meta, StoryObj } from "@storybook/react-vite";
import type { CommandCenterCellData } from "../hooks/useCommandCenterData";
import { CommandCenterPanel } from "./CommandCenterPanel";

const task = {
  id: "task-1",
  task_number: 42,
  slug: "command-center-completion",
  title: "Prepare the launch checklist",
  description: "",
  created_at: "2026-08-28T00:00:00.000Z",
  updated_at: "2026-08-28T00:00:00.000Z",
  origin_product: "code",
} satisfies Task;

const cell = {
  cellIndex: 0,
  taskId: task.id,
  task,
  session: undefined,
  status: "idle",
  repoName: "posthog",
  workspaceMode: "local",
  canvasId: null,
  isBrainrot: false,
  terminalId: null,
  terminalCwd: null,
  hasUnseenCompletion: true,
} satisfies CommandCenterCellData;

const meta = {
  title: "Command center/Task completion",
  component: CommandCenterPanel,
  parameters: { layout: "centered" },
  decorators: [
    (Story) => (
      <div className="h-[360px] w-[640px] overflow-hidden bg-gray-1">
        <Story />
      </div>
    ),
  ],
  args: {
    cell,
    isActiveSession: false,
  },
} satisfies Meta<typeof CommandCenterPanel>;

export default meta;
type Story = StoryObj<typeof meta>;

export const UnseenCompletion: Story = {};

export const SeenCompletion: Story = {
  args: {
    cell: { ...cell, hasUnseenCompletion: false },
  },
};
