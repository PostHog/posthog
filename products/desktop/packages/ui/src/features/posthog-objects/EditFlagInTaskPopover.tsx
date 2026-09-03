import { FlagIcon, ShieldCheckIcon } from "@phosphor-icons/react";
import {
  Button,
  Popover,
  PopoverContent,
  PopoverTrigger,
  Text,
  Textarea,
} from "@posthog/quill";
import { sendPromptToAgent } from "@posthog/ui/features/sessions/sendPromptToAgent";
import { isSendMessageSubmitKey } from "@posthog/ui/utils/sendMessageKey";
import { useCallback, useState } from "react";

/** Appended to every edit so the agent shows the outcome before it writes. */
export const FLAG_EDIT_GUARD =
  "First do a dry run and ask for approval before you change anything.";

export function buildFlagEditPrompt(flagKey: string, request: string): string {
  return `Edit the feature flag \`${flagKey}\`: ${request.trim()}\n\n${FLAG_EDIT_GUARD}`;
}

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
        Edit in task
      </PopoverTrigger>
      <PopoverContent align="end" sideOffset={6} className="w-[420px] p-3.5">
        <Text className="block font-semibold text-[13px]">
          Edit this flag in the task
        </Text>
        <Text variant="muted" className="mt-0.5 block text-xs">
          Describe the change the way you would tell a teammate: who should get
          the flag, and what they should get. The agent works out the rules.
        </Text>

        <div className="mt-3 rounded-lg border border-border bg-card">
          <Textarea
            value={request}
            onChange={(event) => setRequest(event.target.value)}
            onKeyDown={(event) => {
              if (isSendMessageSubmitKey(event)) {
                event.preventDefault();
                void send();
              }
            }}
            placeholder='For example: "Turn this on for the Beta testers cohort too, keep the current person" or "Roll out to 50% of everyone"'
            className="min-h-16 resize-none border-0 bg-transparent px-3 py-2.5 text-[13px] shadow-none focus-visible:ring-0"
            disabled={sending}
          />
          <div className="flex items-center justify-between gap-2 border-border border-t px-2.5 py-2">
            <span className="inline-flex items-center gap-1.5 rounded-md border border-border bg-muted px-2 py-0.5 text-[11.5px] text-foreground">
              <FlagIcon size={11} color="var(--primary)" />
              {flagKey}
            </span>
            <Button
              variant="primary"
              size="sm"
              disabled={!canSend}
              onClick={() => void send()}
            >
              {sending ? "Sending…" : "Send to task"}
            </Button>
          </div>
        </div>

        <div className="mt-3 flex items-start gap-2 rounded-lg border border-border bg-muted px-2.5 py-2 text-muted-foreground text-xs">
          <ShieldCheckIcon size={12} className="mt-0.5 shrink-0" />
          <span>
            Sent with every edit:{" "}
            <span className="font-medium text-foreground">
              “{FLAG_EDIT_GUARD}”
            </span>
          </span>
        </div>
      </PopoverContent>
    </Popover>
  );
}
