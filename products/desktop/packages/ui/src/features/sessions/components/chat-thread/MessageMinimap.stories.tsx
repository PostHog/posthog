import { ChatMessageScrollerProvider } from "@posthog/quill";
import type { ConversationItem } from "@posthog/ui/features/sessions/components/buildConversationItems";
import { MessageMinimap } from "@posthog/ui/features/sessions/components/chat-thread/MessageMinimap";
import { SessionTaskIdProvider } from "@posthog/ui/features/sessions/useSessionTaskId";
import type { Meta, StoryObj } from "@storybook/react-vite";

/** Fixed timestamps keep the rail's tick widths and the row order stable across runs. */
function userMessage(index: number, content: string): ConversationItem {
  return {
    type: "user_message",
    id: `turn-${1700000000000 + index * 60000}-user`,
    content,
    timestamp: 1700000000000 + index * 60000,
  };
}

const ITEMS: ConversationItem[] = [
  userMessage(0, "Why is the minimap popover so wide?"),
  userMessage(
    1,
    "In our minimap of user messages, drop the send time on the right and give the row a link affordance instead — the reader is picking a message here, and what they want from one is a way to send it to someone.",
  ),
  userMessage(2, "Ship it"),
  userMessage(
    3,
    "One more: the same icon should sit under each turn, next to copy.",
  ),
];

const meta = {
  title: "Sessions/MessageMinimap",
  component: MessageMinimap,
  // The minimap parks itself in the scroller's top-right corner, so it needs a positioned box to
  // hug and the scroller context it reads its anchor from.
  decorators: [
    (Story) => (
      <SessionTaskIdProvider taskId="task-1">
        <ChatMessageScrollerProvider>
          <div className="relative h-72 w-[560px] rounded-md border border-(--gray-5) bg-(--color-background)">
            <Story />
          </div>
        </ChatMessageScrollerProvider>
      </SessionTaskIdProvider>
    ),
  ],
} satisfies Meta<typeof MessageMinimap>;

export default meta;
type Story = StoryObj<typeof meta>;

/** The collapsed rail — one tick per user message, width scaled by message length. */
export const Rail: Story = {
  args: { items: ITEMS, anchorId: ITEMS[1].id },
};
