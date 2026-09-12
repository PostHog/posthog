import type { ToolCall } from "@posthog/ui/features/sessions/types";
import type { Meta, StoryObj } from "@storybook/react-vite";
import { ChatThreadChromeProvider } from "./chatThreadChrome";
import { TurnDiffSummary } from "./TurnDiffSummary";

const toolCalls = new Map<string, ToolCall>([
  [
    "edit-settings",
    {
      toolCallId: "edit-settings",
      title: "Edit src/settings.ts",
      kind: "edit",
      status: "completed",
      content: [
        {
          type: "diff",
          path: "src/settings.ts",
          oldText: `export const settings = {
  theme: "light",
};`,
          newText: `export const settings = {
  theme: "system",
  compactMode: true,
};`,
        },
      ],
    },
  ],
  [
    "write-preferences",
    {
      toolCallId: "write-preferences",
      title: "Write src/preferences.ts",
      status: "completed",
      content: [
        {
          type: "diff",
          path: "src/preferences.ts",
          oldText: null,
          newText: `export interface Preferences {
  compactMode: boolean;
}`,
        },
      ],
    },
  ],
]);

const meta: Meta<typeof TurnDiffSummary> = {
  title: "Features/Sessions/TurnDiffSummary",
  component: TurnDiffSummary,
  decorators: [
    (Story) => (
      <ChatThreadChromeProvider value>
        <div className="max-w-3xl">
          <Story />
        </div>
      </ChatThreadChromeProvider>
    ),
  ],
  parameters: {
    layout: "padded",
  },
};

export default meta;
type Story = StoryObj<typeof TurnDiffSummary>;

export const Default: Story = {
  args: {
    toolCalls,
    turnId: "turn-story",
  },
};
