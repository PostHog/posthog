import { readShowActions } from "@posthog/core/sessions/showActions";
import { useHostTRPC } from "@posthog/host-router/react";
import { Button } from "@posthog/quill";
import type { AgentActionAttribution } from "@posthog/shared";
import { ANALYTICS_EVENTS } from "@posthog/shared/analytics-events";
import type { ToolViewProps } from "@posthog/ui/features/sessions/components/session-update/toolCallUtils";
import { useSessionTaskId } from "@posthog/ui/features/sessions/useSessionTaskId";
import { toast } from "@posthog/ui/primitives/toast";
import { track } from "@posthog/ui/shell/analytics";
import { useMutation } from "@tanstack/react-query";
import { useEffect, useMemo } from "react";

function actionAttribution(
  sourceTaskId: string,
  toolCallId: string,
  actionIndex: number,
): AgentActionAttribution {
  return {
    action_id: `${sourceTaskId}:${toolCallId}:${actionIndex}`,
    source_task_id: sourceTaskId,
    tool_call_id: toolCallId,
    action_index: actionIndex,
  };
}

/**
 * The buttons a `show_actions` call offered, drawn where the agent offered them.
 * A click sends the typed action to the host, which builds the link and opens
 * it, so nothing here ever sees or chooses a url.
 */
export function ShowActionsRow({ toolCall }: ToolViewProps) {
  const trpc = useHostTRPC();
  const sourceTaskId = useSessionTaskId();
  const buttons = useMemo(
    () => readShowActions(toolCall.rawInput),
    [toolCall.rawInput],
  );
  useEffect(() => {
    if (!sourceTaskId) return;
    buttons.forEach(({ action }, actionIndex) => {
      track(ANALYTICS_EVENTS.AGENT_ACTION_SHOWN, {
        ...actionAttribution(sourceTaskId, toolCall.toolCallId, actionIndex),
        action_kind: action.kind,
      });
    });
  }, [buttons, sourceTaskId, toolCall.toolCallId]);
  // A click that opens nothing is the failure this tool exists to avoid. One
  // handler covers both ways it happens: the call rejecting leaves `opened`
  // undefined, and the host finding no handler for the link answers false.
  const openAction = useMutation(
    trpc.deepLink.openAgentAction.mutationOptions({
      onSettled: (opened, _error, variables) => {
        if (!opened) {
          toast.error("Couldn't open that");
          track(ANALYTICS_EVENTS.AGENT_ACTION_OPEN_FAILED, {
            ...variables.attribution,
            action_kind: variables.action.kind,
          });
        }
      },
    }),
  );

  if (!sourceTaskId || buttons.length === 0) return null;

  // No surrounding card: the buttons sit in the conversation, which already
  // frames them. A box around them would draw a second frame around nothing.
  return (
    <div className="flex flex-wrap gap-2">
      {buttons.map(({ label, action }, index) => {
        const attribution = actionAttribution(
          sourceTaskId,
          toolCall.toolCallId,
          index,
        );
        return (
          <Button
            key={`${index}-${label}`}
            variant="outline"
            size="sm"
            disabled={openAction.isPending}
            onClick={() => {
              track(ANALYTICS_EVENTS.AGENT_ACTION_CLICKED, {
                ...attribution,
                action_kind: action.kind,
              });
              openAction.mutate({ action, attribution });
            }}
          >
            {label}
          </Button>
        );
      })}
    </div>
  );
}
