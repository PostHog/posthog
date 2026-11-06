import { posthogToolMeta } from "@posthog/shared";
import {
  CreatedPrCard,
  UploadedArtifactCard,
} from "@posthog/ui/features/sessions/components/session-update/InlineArtifactCard";
import type { ToolCall } from "@posthog/ui/features/sessions/types";
import { SessionTaskIdProvider } from "@posthog/ui/features/sessions/useSessionTaskId";
import type { Meta, StoryObj } from "@storybook/react-vite";

const meta: Meta<typeof UploadedArtifactCard> = {
  title: "Sessions/InlineArtifactCard",
  component: UploadedArtifactCard,
  parameters: { layout: "padded" },
  // The cards read the session they are drawn in: without one they have no
  // artifacts panel to send anyone to, and drop the action.
  decorators: [
    (Story) => (
      <SessionTaskIdProvider taskId="task-1">
        <Story />
      </SessionTaskIdProvider>
    ),
  ],
};

export default meta;
type Story = StoryObj<typeof UploadedArtifactCard>;

function uploadCall(status: ToolCall["status"]): ToolCall {
  return {
    toolCallId: "tc-upload",
    kind: "other",
    status,
    title: "upload_artifact",
    rawInput: { path: "/workspace/out/churn-report.csv" },
    _meta: posthogToolMeta({
      toolName: "mcp__posthog-code-tools__upload_artifact",
      mcp: { server: "posthog-code-tools", tool: "upload_artifact" },
    }),
  } as ToolCall;
}

/** The file mid-delivery: the card stands in for it before it exists anywhere. */
export const Uploading: Story = {
  args: { toolCall: uploadCall("in_progress"), turnComplete: false },
  parameters: { testOptions: { waitForLoadersToDisappear: false } },
};

export const Uploaded: Story = {
  args: { toolCall: uploadCall("completed"), turnComplete: true },
};

export const UploadFailed: Story = {
  args: { toolCall: uploadCall("failed"), turnComplete: true },
};

export const PullRequest: StoryObj<typeof CreatedPrCard> = {
  render: () => (
    <CreatedPrCard url="https://github.com/PostHog/posthog/pull/82584" />
  ),
};
