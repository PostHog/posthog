import {
  ArrowLineDownIcon,
  ArrowSquareOutIcon,
  SidebarSimpleIcon,
  SpinnerGapIcon,
} from "@phosphor-icons/react";
import {
  Button,
  Separator,
  Text,
  Tooltip,
  TooltipContent,
  TooltipTrigger,
} from "@posthog/quill";
import { useTaskThread } from "@posthog/ui/features/canvas/hooks/useTaskThread";
import { EmbeddedSessionView } from "@posthog/ui/features/sessions/components/EmbeddedSessionView";
import { taskDetailQuery } from "@posthog/ui/features/tasks/queries";
import { Spin } from "@posthog/ui/primitives/Spinner";
import { useQuery } from "@tanstack/react-query";
import { Link } from "@tanstack/react-router";

/**
 * The agent's dock beside a doc.
 *
 * It is the canvas dock with one thing added: "Add to page". The conversation
 * itself is the app's live session view, so a doc question behaves like every
 * other agent session, and the only way the agent's words reach the page is a
 * person pressing that button.
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
  const { data: task } = useQuery(taskDetailQuery(taskId));
  const { messages } = useTaskThread(taskId);

  const lastAgentMessage = [...messages]
    .reverse()
    .find(
      (message) => message.author_kind === "agent" && message.content.trim(),
    );

  return (
    <div className="flex min-h-0 flex-1 flex-col">
      <div className="flex h-10 shrink-0 items-center gap-1 px-2">
        <Text weight="medium" className="min-w-0 flex-1 truncate px-1">
          Agent
        </Text>
        <Tooltip>
          <TooltipTrigger
            render={
              <Button
                size="icon"
                variant="default"
                aria-label="Open the task"
                render={
                  <Link
                    to="/spaces/$channelId/tasks/$taskId"
                    params={{ channelId, taskId }}
                  />
                }
              />
            }
          >
            <ArrowSquareOutIcon size={15} />
          </TooltipTrigger>
          <TooltipContent>Open the task</TooltipContent>
        </Tooltip>
        <Tooltip>
          <TooltipTrigger
            render={
              <Button
                size="icon"
                variant="default"
                aria-label="Minimize panel"
                onClick={onClose}
              />
            }
          >
            <SidebarSimpleIcon size={16} />
          </TooltipTrigger>
          <TooltipContent>Minimize panel</TooltipContent>
        </Tooltip>
      </div>
      <Separator />

      <div className="min-h-0 flex-1">
        {task ? (
          <EmbeddedSessionView
            task={task}
            isActiveSession
            fixedAgent
            threadActions={() => (
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
            )}
          />
        ) : (
          <div className="flex h-full items-center justify-center">
            <Spin className="text-gray-9">
              <SpinnerGapIcon size={18} />
            </Spin>
          </div>
        )}
      </div>
    </div>
  );
}
