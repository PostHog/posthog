import type { PermissionOption } from "@agentclientprotocol/sdk";
import type { Meta, StoryObj } from "@storybook/react-vite";
import { PlanApprovalSelector } from "./PlanApprovalSelector";
import type { PermissionToolCall } from "./types";

const toolCall = {
  toolCallId: "plan-story",
  title: "Approve this plan to proceed?",
} as PermissionToolCall;

const BYPASS: PermissionOption = {
  kind: "allow_always",
  name: "Yes, bypass all permissions",
  optionId: "bypassPermissions",
};
const AUTO: PermissionOption = {
  kind: "allow_always",
  name: 'Yes, and use "auto" mode',
  optionId: "auto",
};
const ACCEPT_EDITS: PermissionOption = {
  kind: "allow_always",
  name: "Yes, and auto-accept edits",
  optionId: "acceptEdits",
};
const DEFAULT_MODE: PermissionOption = {
  kind: "allow_once",
  name: "Yes, and manually approve edits",
  optionId: "default",
};
const REJECT: PermissionOption = {
  kind: "reject_once",
  name: "No, and tell the agent what to do differently",
  optionId: "reject_with_feedback",
  _meta: { customInput: true },
};

const meta: Meta<typeof PlanApprovalSelector> = {
  title: "Components/Permissions/PlanApprovalSelector",
  component: PlanApprovalSelector,
  parameters: { layout: "padded" },
  args: { toolCall },
  argTypes: {
    onSelect: { action: "selected" },
    onCancel: { action: "cancelled" },
  },
};

export default meta;
type Story = StoryObj<typeof PlanApprovalSelector>;

// Non-root / non-sandbox: bypass is not offered. Default is "manually approve".
export const Default: Story = {
  args: { options: [AUTO, ACCEPT_EDITS, DEFAULT_MODE, REJECT] },
};

// Sandbox / root: bypass is offered but still not the default.
export const WithBypass: Story = {
  args: { options: [BYPASS, AUTO, ACCEPT_EDITS, DEFAULT_MODE, REJECT] },
};
