import type { Meta, StoryObj } from "@storybook/react-vite";
import { CanvasConnectorPermissionPrompt } from "./CanvasConnectorPermissionPrompt";

const meta: Meta<typeof CanvasConnectorPermissionPrompt> = {
  title: "Canvas/Connector permission",
  component: CanvasConnectorPermissionPrompt,
  args: { onRespond: () => {} },
};
export default meta;
type Story = StoryObj<typeof CanvasConnectorPermissionPrompt>;

export const CanvasAccess: Story = {
  args: {
    request: {
      provider: "github",
      tool: "list_pull_requests",
      reason: "canvas",
    },
  },
};
export const ToolApproval: Story = {
  args: {
    request: {
      provider: "mcp:calendar.example.com",
      tool: "list_events",
      arguments: { limit: 5 },
      reason: "tool",
    },
  },
};
