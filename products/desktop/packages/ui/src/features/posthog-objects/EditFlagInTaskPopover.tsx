import {
  Button,
  Popover,
  PopoverContent,
  PopoverTrigger,
  Text,
  Textarea,
} from "@posthog/quill";
import { sendPromptToAgent } from "@posthog/ui/features/sessions/sendPromptToAgent";
import { toast } from "@posthog/ui/primitives/toast";
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
        toast.success("Sent to the task");
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
      <PopoverContent align="end" sideOffset={8} className="w-[400px] p-4">
        <Text className="block font-semibold text-[13px]">
          Describe the change
        </Text>
        <Text variant="muted" className="mt-0.5 block text-xs">
          Say who gets the flag and what they get.
        </Text>
        <Textarea
          autoFocus
          rows={3}
          value={request}
          onChange={(event) => setRequest(event.target.value)}
          onKeyDown={(event) => {
            if (isSendMessageSubmitKey(event)) {
              event.preventDefault();
              void send();
            }
          }}
          placeholder="For example: Turn this on for the Beta testers cohort too."
          className="mt-3 resize-none text-[13px]"
          disabled={sending}
        />
        <div className="mt-3 flex justify-end">
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
      </PopoverContent>
    </Popover>
  );
}
