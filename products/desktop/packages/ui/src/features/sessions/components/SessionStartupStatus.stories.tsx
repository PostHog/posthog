import { useProvisioningStore } from "@posthog/ui/features/provisioning/store";
import type { Meta, StoryObj } from "@storybook/react-vite";
import { SessionProvisioningStatus } from "./SessionProvisioningStatus";
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
export const Reconnecting: Story = {
  args: { label: "Connecting to agent..." },
};
export const WithDetail: Story = {
  args: { detail: "Cloning repository..." },
};

const PROVISIONING_TASK_ID = "story-provisioning";

export const Provisioning: Story = {
  parameters: { layout: "fullscreen" },
  decorators: [
    (Story) => {
      useProvisioningStore.setState({
        output: {
          [PROVISIONING_TASK_ID]: [
            "Cloning into /tasks/story-provisioning...",
            "Installing dependencies",
          ],
        },
      });
      return <Story />;
    },
  ],
  render: () => (
    <div className="flex h-screen min-h-[420px] w-full items-end justify-center bg-background pb-10">
      <div className="w-full max-w-xl">
        <SessionProvisioningStatus
          executionTarget="local"
          taskId={PROVISIONING_TASK_ID}
        />
      </div>
    </div>
  ),
};
