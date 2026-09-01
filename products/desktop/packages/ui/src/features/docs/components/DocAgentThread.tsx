import {
  ArrowLineDownIcon,
  ArrowSquareOutIcon,
  XIcon,
} from "@phosphor-icons/react";
import { Button, cn, Separator, Spinner, Text, Textarea } from "@posthog/quill";
import type { TaskThreadMessage } from "@posthog/shared/domain-types";
import {
  usePostTaskThreadMessageToAgent,
  useTaskThread,
} from "@posthog/ui/features/canvas/hooks/useTaskThread";
import { Link } from "@tanstack/react-router";
import { useState } from "react";

/**
 * An agent conversation beside a doc.
 *
 * The thread is a task in this space, so it behaves like every other agent
 * session. Two things are specific to a doc: the thread draws from the durable
 * messages rather than waiting for a live session, and "Add to page" is the only
 * way the agent's words reach the page.
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
  const { messages, hasLoaded } = useTaskThread(taskId);
  const { postMessageToAgent, isPostingToAgent } =
    usePostTaskThreadMessageToAgent(taskId);
  const [draft, setDraft] = useState("");

  const said = messages.filter((message) => message.content.trim());
  const lastAgentMessage = [...said]
    .reverse()
    .find((message) => message.author_kind === "agent");

  const send = async () => {
    const content = draft.trim();
    if (!content || isPostingToAgent) return;
    await postMessageToAgent(content);
    setDraft("");
  };

  return (
    <div className="flex min-h-0 flex-1 flex-col">
      <div className="flex items-center justify-between gap-2 px-3 py-2">
        <Text weight="medium">Agent</Text>
        <div className="flex items-center gap-1">
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
          <Button
            size="sm"
            variant="default"
            aria-label="Open the task"
            render={
              <Link
                to="/spaces/$channelId/tasks/$taskId"
                params={{ channelId, taskId }}
              />
            }
          >
            <ArrowSquareOutIcon size={14} />
          </Button>
          <Button
            size="sm"
            variant="default"
            aria-label="Close the agent thread"
            onClick={onClose}
          >
            <XIcon size={14} />
          </Button>
        </div>
      </div>
      <Separator />

      <div className="min-h-0 flex-1 overflow-y-auto p-3">
        {!hasLoaded ? (
          <div className="flex justify-center py-8">
            <Spinner />
          </div>
        ) : said.length === 0 ? (
          <Text size="sm" className="text-(--gray-11)">
            The question is on its way to the agent. Its answer shows up here.
          </Text>
        ) : (
          <ul className="flex flex-col gap-3">
            {said.map((message) => (
              <ThreadMessage key={message.id} message={message} />
            ))}
          </ul>
        )}
        {said.length > 0 && !lastAgentMessage ? (
          <Text size="sm" className="mt-3 block text-(--gray-11)">
            The agent has not answered yet. "Add to page" turns on when it does.
          </Text>
        ) : null}
      </div>

      <Separator />
      <div className="p-3">
        <Textarea
          value={draft}
          onChange={(event) => setDraft(event.target.value)}
          placeholder="Ask the agent something else"
          rows={2}
          className="text-sm"
        />
        <div className="mt-1 flex justify-end">
          <Button
            size="sm"
            variant="primary"
            loading={isPostingToAgent}
            disabled={isPostingToAgent || draft.trim().length === 0}
            onClick={() => void send()}
          >
            Send
          </Button>
        </div>
      </div>
    </div>
  );
}

function ThreadMessage({ message }: { message: TaskThreadMessage }) {
  const fromAgent = message.author_kind === "agent";
  const name = fromAgent
    ? "Agent"
    : `${message.author?.first_name ?? ""} ${message.author?.last_name ?? ""}`.trim() ||
      message.author?.email ||
      "Someone";

  return (
    <li
      className={cn(
        "rounded-(--radius-3) border p-2",
        fromAgent ? "border-(--blue-7)" : "border-(--gray-6)",
      )}
    >
      <Text size="sm" weight="medium">
        {name}
        <span className="ml-1 font-normal text-(--gray-11) text-xs">
          {new Date(message.created_at).toLocaleString()}
        </span>
      </Text>
      <Text size="sm" className="whitespace-pre-wrap">
        {message.content}
      </Text>
    </li>
  );
}
