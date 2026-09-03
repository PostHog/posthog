import { readShowActions } from "@posthog/core/sessions/showActions";
import { useHostTRPC } from "@posthog/host-router/react";
import { Button } from "@posthog/quill";
import { ANALYTICS_EVENTS } from "@posthog/shared";
import type { ToolViewProps } from "@posthog/ui/features/sessions/components/session-update/toolCallUtils";
import { useSessionTaskId } from "@posthog/ui/features/sessions/useSessionTaskId";
import {
  getCachedTask,
  getCachedTaskDetail,
} from "@posthog/ui/features/tasks/queries";
import { toast } from "@posthog/ui/primitives/toast";
import { track } from "@posthog/ui/shell/analytics";
import { useMutation } from "@tanstack/react-query";

// Read from cache only. A click must not wait on a fetch, and the task is
// already loaded by whatever drew the conversation around this row.
function readTaskOriginKey(taskId: string | null): string | null {
  if (!taskId) return null;
  const task = getCachedTaskDetail(taskId) ?? getCachedTask(taskId);
  return task?.origin_key ?? null;
}

/**
 * The buttons a `show_actions` call offered, drawn where the agent offered them.
 * A click sends the typed action to the host, which builds the link and opens
 * it, so nothing here ever sees or chooses a url.
 */
export function ShowActionsRow({ toolCall }: ToolViewProps) {
  const trpc = useHostTRPC();
  const taskId = useSessionTaskId();
  // A click that opens nothing is the failure this tool exists to avoid. One
  // handler covers both ways it happens: the call rejecting leaves `opened`
  // undefined, and the host finding no handler for the link answers false.
  // The same handler captures the click, because every action kind navigates
  // out of the session and nothing downstream sees the choice.
  const openAction = useMutation(
    trpc.deepLink.openAgentAction.mutationOptions({
      onSettled: (opened, _error, variables) => {
        if (!opened) toast.error("Couldn't open that");
        track(ANALYTICS_EVENTS.AGENT_ACTION_CLICKED, {
          action_kind: variables.action.kind,
          task_id: taskId,
          task_origin_key: readTaskOriginKey(taskId),
          opened: Boolean(opened),
        });
      },
    }),
  );
  const buttons = readShowActions(toolCall.rawInput);

  if (buttons.length === 0) return null;

  // No surrounding card: the buttons sit in the conversation, which already
  // frames them. A box around them would draw a second frame around nothing.
  return (
    <div className="flex flex-wrap gap-2">
      {buttons.map(({ label, action }, index) => (
        <Button
          key={`${index}-${label}`}
          variant="outline"
          size="sm"
          disabled={openAction.isPending}
          onClick={() => openAction.mutate({ action })}
        >
          {label}
        </Button>
      ))}
    </div>
  );
}
