import { useProvisioningStore } from "@posthog/ui/features/provisioning/store";
import type { Meta, StoryObj } from "@storybook/react-vite";
import { SessionProvisioningStatus } from "./SessionProvisioningStatus";
import { SessionStartupStatus, startupLabel } from "./SessionStartupStatus";

const meta = {
  title: "Sessions/Startup status",
  component: SessionStartupStatus,
  parameters: { layout: "centered" },
  args: { label: startupLabel("local") },
} satisfies Meta<typeof SessionStartupStatus>;

export default meta;
type Story = StoryObj<typeof meta>;

export const StartingLocalAgent: Story = {};
export const RunningSetup: Story = {
  args: { label: startupLabel("local", "setup_hooks") },
};
export const StartingCloudAgent: Story = {
  args: { label: startupLabel("cloud") },
};
export const Reconnecting: Story = {
  args: { label: "Connecting to agent..." },
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
    <div className="min-h-[420px] w-full bg-background p-6">
      <div className="mx-auto w-full max-w-[750px]">
        <p className="mb-6 text-sm">
          Sure. I will start by reading the setup script.
        </p>
        <SessionProvisioningStatus
          executionTarget="local"
          taskId={PROVISIONING_TASK_ID}
        />
      </div>
    </div>
  ),
};
