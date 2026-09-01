import { ArrowLineDownIcon } from "@phosphor-icons/react";
import { Button, Separator, Text } from "@posthog/quill";
import { ThreadPanel } from "@posthog/ui/features/canvas/components/ThreadPanel";
import { useTaskThread } from "@posthog/ui/features/canvas/hooks/useTaskThread";

/**
 * An agent conversation beside a doc.
 *
 * The thread is a task in this space, so it behaves like every other agent
 * session. The one thing this surface adds is the way out: "Add to page" takes
 * the agent's last answer and puts it in the doc, which is the only way agent
 * text ever reaches the page.
 */
export function DocAgentThread({
  taskId,
  channelId,
  onAddToPage,
  onClose,
}: {
  taskId: string;
  channelId: string;
  onAddToPage: (text: string) => void;
  onClose: () => void;
}) {
  const { messages } = useTaskThread(taskId);
  const lastAgentMessage = [...messages]
    .reverse()
    .find(
      (message) => message.author_kind === "agent" && message.content.trim(),
    );

  return (
    <div className="flex min-h-0 flex-1 flex-col">
      <div className="flex items-center justify-between gap-2 px-3 py-2">
        <Text weight="medium">Agent</Text>
        <Button
          size="sm"
          variant="default"
          disabled={!lastAgentMessage}
          onClick={() =>
            lastAgentMessage && onAddToPage(lastAgentMessage.content)
          }
        >
          <ArrowLineDownIcon size={14} />
          Add to page
        </Button>
      </div>
      {!lastAgentMessage ? (
        <Text size="sm" className="px-3 pb-2 text-(--gray-11)">
          Nothing to add yet. The button turns on when the agent answers.
        </Text>
      ) : null}
      <Separator />
      <div className="min-h-0 flex-1">
        <ThreadPanel
          taskId={taskId}
          channelId={channelId}
          onClose={onClose}
          showTaskSummary={false}
        />
      </div>
    </div>
  );
}
