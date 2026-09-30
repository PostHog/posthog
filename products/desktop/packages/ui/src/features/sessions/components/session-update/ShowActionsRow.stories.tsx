import { ShowActionsRow } from "@posthog/ui/features/sessions/components/session-update/ShowActionsRow";
import type { ToolCall } from "@posthog/ui/features/sessions/types";
import type { Meta, StoryObj } from "@storybook/react-vite";

function showActionsCall(actions: unknown[]): ToolCall {
  return {
    toolCallId: "story-show-actions",
    rawInput: { actions },
    status: "completed",
  } as ToolCall;
}

const meta: Meta<typeof ShowActionsRow> = {
  title: "Features/Sessions/ShowActionsRow",
  component: ShowActionsRow,
  parameters: {
    layout: "padded",
  },
};

export default meta;
type Story = StoryObj<typeof ShowActionsRow>;

export const Pills: Story = {
  args: {
    toolCall: showActionsCall([
      {
        kind: "compose",
        label: "Fix the login bug",
        prompt: "Fix the login redirect loop on session expiry",
      },
      { kind: "open_space", label: "Open #growth", channel_id: "chan-1" },
      {
        kind: "open_canvas",
        label: "Explore PostHog Desktop",
        channel_id: "chan-1",
        canvas_id: "canvas-1",
      },
      { kind: "open_inbox", label: "Review findings" },
    ]),
    turnComplete: true,
  },
};

// A compose action with a description renders as a card; the rest stay pills.
export const CardsAndPills: Story = {
  args: {
    toolCall: showActionsCall([
      {
        kind: "compose",
        label: "Add PostHog to your app",
        description:
          "Opens a task that instruments your codebase and files a PR to review",
        prompt: "Add PostHog analytics to my app and open a pull request",
      },
      {
        kind: "compose",
        label: "Set up error tracking",
        description: "Wires exception capture into your existing SDK setup",
        prompt: "Enable PostHog error tracking in my app",
      },
      { kind: "open_inbox", label: "Review findings" },
      { kind: "open_space", label: "Open #growth", channel_id: "chan-1" },
    ]),
    turnComplete: true,
  },
};

export const SingleCard: Story = {
  args: {
    toolCall: showActionsCall([
      {
        kind: "compose",
        label: "Add PostHog to your app",
        description:
          "Opens a task that instruments your codebase and files a PR to review",
        prompt: "Add PostHog analytics to my app and open a pull request",
      },
    ]),
    turnComplete: true,
  },
};
