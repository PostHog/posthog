import {
  FlagIcon,
  PencilSimpleIcon,
  ShieldCheckIcon,
} from "@phosphor-icons/react";
import {
  Button,
  Kbd,
  KbdGroup,
  Popover,
  PopoverContent,
  PopoverTrigger,
  Text,
  Textarea,
} from "@posthog/quill";
import { sendPromptToAgent } from "@posthog/ui/features/sessions/sendPromptToAgent";
import { useSettingsStore } from "@posthog/ui/features/settings/settingsStore";
import { toast } from "@posthog/ui/primitives/toast";
import { isSendMessageSubmitKey } from "@posthog/ui/utils/sendMessageKey";
import { useCallback, useState } from "react";

/** Appended to every edit so the agent shows the outcome before it writes. */
export const FLAG_EDIT_GUARD =
  "First do a dry run and ask for approval before you change anything.";

export function buildFlagEditPrompt(flagKey: string, request: string): string {
  return `Edit the feature flag \`${flagKey}\`: ${request.trim()}\n\n${FLAG_EDIT_GUARD}`;
}

const EXAMPLE_REQUEST =
  "Turn this on for the Beta testers cohort as well, and keep the current person.";

/**
 * Sends a plain-language change request for a flag back into the task the
 * flag appears in. The agent dry-runs and asks before it applies anything.
 */
export function EditFlagInTaskPopover({
  taskId,
  flagKey,
}: {
  taskId: string;
  flagKey: string;
}) {
  const [open, setOpen] = useState(false);
  const [request, setRequest] = useState("");
  const [sending, setSending] = useState(false);
  const sendMessagesWith = useSettingsStore((state) => state.sendMessagesWith);
  const canSend = request.trim().length > 0 && !sending;

  const send = useCallback(async () => {
    if (!canSend) return;
    setSending(true);
    try {
      const sent = await sendPromptToAgent(
        taskId,
        buildFlagEditPrompt(flagKey, request),
      );
      if (sent) {
        setRequest("");
        setOpen(false);
        toast.success("Sent to the task", {
          description:
            "The agent will show a dry run before it changes the flag.",
        });
      }
    } finally {
      setSending(false);
    }
  }, [canSend, taskId, flagKey, request]);

  return (
    <Popover open={open} onOpenChange={setOpen}>
      <PopoverTrigger
        render={
          <Button
            variant="primary"
            size="sm"
            data-attr="posthog-object-edit-flag-in-task"
          />
        }
      >
        <PencilSimpleIcon size={13} weight="bold" />
        Edit in task
      </PopoverTrigger>
      <PopoverContent align="end" sideOffset={8} className="w-[440px] p-0">
        <div className="px-4 pt-3.5 pb-3">
          <div className="flex items-center gap-2">
            <Text className="font-semibold text-[13px]">
              Describe the change
            </Text>
            <span className="inline-flex items-center gap-1 rounded-md border border-border bg-muted px-1.5 py-px font-mono text-[11px] text-foreground">
              <FlagIcon size={10} weight="fill" color="var(--primary)" />
              {flagKey}
            </span>
          </div>
          <Text variant="muted" className="mt-1 block text-xs leading-relaxed">
            Say who should get the flag and what they should get. The agent
            turns that into release conditions in the task this flag came from.
          </Text>
        </div>

        <div className="px-4">
          <div className="rounded-lg border border-border bg-card shadow-xs transition-shadow focus-within:border-(--primary) focus-within:shadow-[0_0_0_3px_var(--primary-a4,rgba(0,0,0,0.06))]">
            <Textarea
              autoFocus
              value={request}
              onChange={(event) => setRequest(event.target.value)}
              onKeyDown={(event) => {
                if (isSendMessageSubmitKey(event)) {
                  event.preventDefault();
                  void send();
                }
              }}
              placeholder={`For example: "${EXAMPLE_REQUEST}"`}
              className="min-h-20 resize-none border-0 bg-transparent px-3 py-2.5 text-[13px] shadow-none focus-visible:ring-0"
              disabled={sending}
            />
            <div className="flex items-center justify-between gap-2 border-border border-t px-2.5 py-2">
              <KbdGroup className="text-[11px] text-muted-foreground">
                {sendMessagesWith === "cmd+enter" && <Kbd>⌘</Kbd>}
                <Kbd>↵</Kbd>
                <span className="ml-1">to send</span>
              </KbdGroup>
              <Button
                variant="primary"
                size="sm"
                loading={sending}
                disabled={!canSend}
                onClick={() => void send()}
              >
                Send to task
              </Button>
            </div>
          </div>
        </div>

        <div className="mt-3 border-border border-t bg-muted px-4 py-2.5">
          <div className="flex items-start gap-2 text-muted-foreground text-xs leading-relaxed">
            <ShieldCheckIcon
              size={13}
              weight="fill"
              className="mt-px shrink-0 text-(--green-9)"
            />
            <span>
              Nothing changes without your approval. Every request ends with:{" "}
              <span className="text-foreground">“{FLAG_EDIT_GUARD}”</span>
            </span>
          </div>
        </div>
      </PopoverContent>
    </Popover>
  );
}
