import {
  ChatBubble,
  ChatBubbleContent,
  ChatMessage,
  ChatMessageContent,
} from "@posthog/quill";
import type { Meta, StoryObj } from "@storybook/react-vite";
import { FailedMessageResendAction } from "./FailedMessageResend";

const meta = {
  title: "Features/Sessions/Failed message",
  component: FailedMessageResendAction,
  parameters: { layout: "centered" },
  args: { onResend: async () => {} },
} satisfies Meta<typeof FailedMessageResendAction>;

export default meta;
type Story = StoryObj<typeof meta>;

export const InConversation: Story = {
  render: (args) => (
    <div className="flex w-[min(100vw,32rem)] flex-col gap-5 rounded-lg border p-4">
      <ChatMessage align="start">
        <ChatMessageContent>I'll check the delivery path.</ChatMessageContent>
      </ChatMessage>
      <ChatMessage align="end">
        <ChatMessageContent>
          <ChatBubble align="end" variant="default">
            <ChatBubbleContent>
              Can you check the queued messages too?
            </ChatBubbleContent>
          </ChatBubble>
          <FailedMessageResendAction {...args} />
        </ChatMessageContent>
      </ChatMessage>
      <ChatMessage align="start">
        <ChatMessageContent>The run has finished.</ChatMessageContent>
      </ChatMessage>
    </div>
  ),
};
