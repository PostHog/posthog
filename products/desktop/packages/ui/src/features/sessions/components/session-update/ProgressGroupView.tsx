import { CaretDown, CaretRight, ListChecks } from "@phosphor-icons/react";
import { type Step, StepList } from "@posthog/ui/primitives/StepList";
import * as Collapsible from "@radix-ui/react-collapsible";
import { Box, Text } from "@radix-ui/themes";
import { useEffect, useState } from "react";
import { useChatThreadChrome } from "../chat-thread/chatThreadChrome";
import { ToolRow } from "./ToolRow";

interface ProgressGroupViewProps {
  steps: Step[];
  /** True while at least one step in this group is `in_progress`. */
  isActive: boolean;
  /** True once the enclosing turn has finished. Drives the auto-collapse. */
  turnComplete?: boolean;
}

// Header label follows the stream: the currently in-flight step's label if
// any, otherwise the last step seen. No hardcoded fallbacks — the backend
// controls all wording, including present-tense during `in_progress`.
function resolveHeaderLabel(steps: Step[]): string | null {
  if (steps.length === 0) return null;
  const active = steps.find((s) => s.status === "in_progress");
  if (active) return active.label;
  return steps[steps.length - 1].label;
}

export function ProgressGroupView({
  steps,
  isActive,
  turnComplete,
}: ProgressGroupViewProps) {
  const [userToggledOpen, setUserToggledOpen] = useState<boolean | null>(null);
  // New thread renders the group through the shared `ToolRow` (ChatMarker chrome); the legacy thread
  // keeps its bespoke Radix collapsible so ConversationView is unchanged when the chat thread is off.
  const chatChrome = useChatThreadChrome();

  useEffect(() => {
    // Any reactivation clears the sticky user choice so a new round of work
    // starts expanded again.
    if (isActive) setUserToggledOpen(null);
  }, [isActive]);

  if (steps.length === 0) return null;

  const hasHeader = steps.length > 1;

  // Legacy thread: bespoke collapsible header (caret + summary). While the turn is still running the
  // trigger is disabled and forced open, so the user sees progress stream in without a flicker between
  // consecutive step transitions. Once the turn completes, the header auto-collapses (default: open)
  // and becomes interactive. Single-step groups have no header — the one step row IS the whole view.
  if (!chatChrome) {
    const isOpen = !hasHeader
      ? true
      : !turnComplete
        ? true
        : (userToggledOpen ?? true);
    const summaryLabel = resolveHeaderLabel(steps) ?? "";

    return (
      <Box className="my-1">
        <Collapsible.Root
          open={isOpen}
          onOpenChange={(next) => {
            if (hasHeader && turnComplete) setUserToggledOpen(next);
          }}
        >
          {hasHeader && (
            <Collapsible.Trigger asChild disabled={!turnComplete}>
              <button
                type="button"
                className="flex w-full items-center gap-2 rounded-sm px-1 py-0.5 text-left enabled:hover:bg-gray-3 disabled:cursor-default"
              >
                {isOpen ? (
                  <CaretDown size={12} className="text-gray-10" />
                ) : (
                  <CaretRight size={12} className="text-gray-10" />
                )}
                <Text className="font-medium text-gray-12 text-sm">
                  {summaryLabel}
                </Text>
              </button>
            </Collapsible.Trigger>
          )}
          <Collapsible.Content>
            <Box pl={hasHeader ? "4" : "0"} py="1">
              <StepList steps={steps} />
            </Box>
          </Collapsible.Content>
        </Collapsible.Root>
      </Box>
    );
  }

  // New thread: single-step groups have no header, so their body must stay expanded — collapsing with
  // no header would leave nothing on screen.
  if (!hasHeader) {
    return (
      <Box className="my-1">
        <StepList steps={steps} />
      </Box>
    );
  }

  // Multi-step groups stay open while the turn is running, then honour the user
  // toggle once the turn completes (default: collapsed).
  const isOpen = !turnComplete ? true : (userToggledOpen ?? false);
  const summaryLabel = resolveHeaderLabel(steps) ?? "";

  return (
    <ToolRow
      icon={ListChecks}
      isLoading={isActive}
      open={isOpen}
      onOpenChange={(next) => {
        // Only the user's choice (after the turn finishes) sticks; while running
        // the row is controlled open, so a stray toggle is ignored.
        if (turnComplete) setUserToggledOpen(next);
      }}
      content={<StepList steps={steps} />}
    >
      {summaryLabel}
    </ToolRow>
  );
}
