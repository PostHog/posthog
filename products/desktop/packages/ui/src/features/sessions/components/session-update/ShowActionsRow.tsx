import {
  Hash,
  type Icon,
  Layout,
  PencilSimple,
  Tray,
} from "@phosphor-icons/react";
import { readShowActions } from "@posthog/core/sessions/showActions";
import { useHostTRPC } from "@posthog/host-router/react";
import { Button, Text } from "@posthog/quill";
import type { ShowActionButton } from "@posthog/shared";
import type { ToolViewProps } from "@posthog/ui/features/sessions/components/session-update/toolCallUtils";
import { toast } from "@posthog/ui/primitives/toast";
import { useMutation } from "@tanstack/react-query";

// The UI picks the icon and accent from the verb, so the agent never gets to
// choose either and every button of a kind looks the same everywhere.
const ACTION_LOOKS: Record<
  ShowActionButton["action"]["kind"],
  { icon: Icon; color: string }
> = {
  compose: { icon: PencilSimple, color: "blue" },
  open_canvas: { icon: Layout, color: "purple" },
  open_inbox: { icon: Tray, color: "orange" },
  open_space: { icon: Hash, color: "green" },
};

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

  // Consecutive same-shape buttons form one run, so the agent's order
  // survives: a pill before a card still renders before that card.
  const runs: ShowActionButton[][] = [];
  for (const button of buttons) {
    const isCard = Boolean(button.description);
    const lastRun = runs.at(-1);
    if (lastRun && Boolean(lastRun[0].description) === isCard) {
      lastRun.push(button);
    } else {
      runs.push([button]);
    }
  }

  // No surrounding card: the buttons sit in the conversation, which already
  // frames them. A box around them would draw a second frame around nothing.
  return (
    <div className="flex flex-col gap-2">
      {runs.map((run) =>
        run[0].description ? (
          <div
            key={`${run[0].label}-${run[0].action.kind}`}
            className="flex max-w-sm flex-col gap-2"
          >
            {run.map(({ label, description, action }) => {
              const { icon: ActionIcon, color } = ACTION_LOOKS[action.kind];
              return (
                <button
                  key={`${label}-${action.kind}`}
                  type="button"
                  disabled={openAction.isPending}
                  onClick={() => openAction.mutate({ action })}
                  style={
                    {
                      "--card-hover-border": `var(--${color}-6)`,
                    } as React.CSSProperties
                  }
                  className="flex w-full cursor-pointer items-start gap-2.5 rounded-xl border border-(--gray-a3) bg-(--color-panel-solid) px-2.5 py-2 text-left shadow-[0_1px_3px_rgba(0,0,0,0.04),0_1px_2px_rgba(0,0,0,0.02)] transition-[border-color,box-shadow] hover:border-(--card-hover-border) hover:shadow-[0_2px_8px_rgba(0,0,0,0.06),0_1px_3px_rgba(0,0,0,0.04)] disabled:cursor-default disabled:opacity-60"
                >
                  <div
                    className="flex h-6 w-6 shrink-0 items-center justify-center rounded-md"
                    style={{ backgroundColor: `var(--${color}-3)` }}
                  >
                    <ActionIcon
                      size={14}
                      weight="duotone"
                      color={`var(--${color}-9)`}
                      aria-hidden
                    />
                  </div>
                  <div className="flex min-w-0 flex-1 flex-col gap-1">
                    <Text
                      size="xs"
                      weight="medium"
                      className="min-w-0 truncate text-(--gray-12)"
                    >
                      {label}
                    </Text>
                    <Text
                      size="xs"
                      className="line-clamp-1 text-(--gray-11) leading-normal"
                    >
                      {description}
                    </Text>
                  </div>
                </button>
              );
            })}
          </div>
        ) : (
          <div
            key={`${run[0].label}-${run[0].action.kind}`}
            className="flex flex-wrap gap-2"
          >
            {run.map(({ label, action }) => {
              const { icon: ActionIcon, color } = ACTION_LOOKS[action.kind];
              return (
                <Button
                  key={`${label}-${action.kind}`}
                  variant="outline"
                  size="sm"
                  disabled={openAction.isPending}
                  onClick={() => openAction.mutate({ action })}
                >
                  <ActionIcon
                    size={14}
                    weight="duotone"
                    color={`var(--${color}-9)`}
                    aria-hidden
                  />
                  {label}
                </Button>
              );
            })}
          </div>
        ),
      )}
    </div>
  );
}
