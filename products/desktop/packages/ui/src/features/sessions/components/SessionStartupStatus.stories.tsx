import type { Meta, StoryObj } from "@storybook/react-vite";
import { PendingChatView } from "./PendingChatView";
import { SessionStartupStatus } from "./SessionStartupStatus";

const meta = {
  title: "Sessions/Startup status",
  component: SessionStartupStatus,
  parameters: { layout: "centered" },
  args: { executionTarget: "local" },
} satisfies Meta<typeof SessionStartupStatus>;

export default meta;
type Story = StoryObj<typeof meta>;

export const StartingAgent: Story = {};
export const RunningSetup: Story = { args: { phase: "setup_hooks" } };
export const Cloud: Story = { args: { executionTarget: "cloud" } };

export const PendingWorktree: Story = {
  args: { phase: "setup_hooks" },
  parameters: { layout: "fullscreen" },
  render: (args) => (
    <div className="relative h-screen min-h-[420px] w-full bg-background">
      <PendingChatView
        content="Add keyboard navigation to the project list."
        executionTarget={args.executionTarget}
        phase={args.phase}
      />
    </div>
  ),
};
