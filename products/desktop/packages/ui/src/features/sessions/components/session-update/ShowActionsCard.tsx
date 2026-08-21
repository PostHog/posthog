import { useHostTRPC } from "@posthog/host-router/react";
import { Button, Card, CardContent } from "@posthog/quill";
import { readShowActions } from "@posthog/ui/features/sessions/components/session-update/inlineArtifacts";
import type { ToolViewProps } from "@posthog/ui/features/sessions/components/session-update/toolCallUtils";
import { useMutation } from "@tanstack/react-query";

/**
 * The buttons a `show_actions` call offered, drawn where the agent offered them.
 * A click sends the typed action to the host, which builds the link and opens
 * it — the card never sees or chooses a url.
 */
export function ShowActionsCard({ toolCall }: ToolViewProps) {
  const trpc = useHostTRPC();
  const openAction = useMutation(
    trpc.deepLink.openAgentAction.mutationOptions(),
  );
  const buttons = readShowActions(toolCall.rawInput);

  if (buttons.length === 0) return null;

  return (
    <Card>
      <CardContent className="flex flex-wrap gap-2 p-3">
        {buttons.map(({ label, action }, index) => (
          <Button
            key={`${index}-${label}`}
            variant="outline"
            disabled={openAction.isPending}
            onClick={() => openAction.mutate({ action })}
          >
            {label}
          </Button>
        ))}
      </CardContent>
    </Card>
  );
}
