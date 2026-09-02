import { readShowActions } from "@posthog/core/sessions/showActions";
import { useHostTRPC } from "@posthog/host-router/react";
import { Button } from "@posthog/quill";
import type { ToolViewProps } from "@posthog/ui/features/sessions/components/session-update/toolCallUtils";
import { toast } from "@posthog/ui/primitives/toast";
import { useMutation } from "@tanstack/react-query";

/**
 * The buttons a `show_actions` call offered, drawn where the agent offered them.
 * A click sends the typed action to the host, which builds the link and opens
 * it, so nothing here ever sees or chooses a url.
 */
export function ShowActionsRow({ toolCall }: ToolViewProps) {
  const trpc = useHostTRPC();
  // A click that opens nothing is the failure this tool exists to avoid. One
  // handler covers both ways it happens: the call rejecting leaves `opened`
  // undefined, and the host finding no handler for the link answers false.
  const openAction = useMutation(
    trpc.deepLink.openAgentAction.mutationOptions({
      onSettled: (opened) => {
        if (!opened) toast.error("Couldn't open that");
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
