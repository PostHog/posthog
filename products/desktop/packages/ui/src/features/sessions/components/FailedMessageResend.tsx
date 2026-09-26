import {
  SESSION_SERVICE,
  type SessionService,
} from "@posthog/core/sessions/sessionService";
import { useService } from "@posthog/di/react";
import { Button } from "@posthog/quill";
import { toast } from "@posthog/ui/primitives/toast";
import { type ReactElement, useState } from "react";

export function FailedMessageResendAction({
  onResend,
  truncated = false,
  resendable = true,
}: {
  onResend: () => Promise<void>;
  truncated?: boolean;
  resendable?: boolean;
}): ReactElement {
  const [sending, setSending] = useState(false);

  const resend = async (): Promise<void> => {
    if (sending || truncated || !resendable) return;
    setSending(true);
    try {
      await onResend();
    } catch {
      toast.error("Could not resend message. Try again.");
    } finally {
      setSending(false);
    }
  };

  return (
    <span className="flex items-center justify-end gap-2 text-red-11 text-xs">
      <span>
        {truncated
          ? "Did not reach the agent. Message shortened; resend unavailable."
          : !resendable
            ? "Did not reach the agent. Attached files unavailable; resend unavailable."
            : "Did not reach the agent"}
      </span>
      {!truncated && resendable && (
        <Button
          variant="link-muted"
          size="sm"
          loading={sending}
          disabled={sending}
          onClick={resend}
        >
          Resend
        </Button>
      )}
    </span>
  );
}

export function FailedMessageResend({
  taskId,
  content,
  truncated,
  resendable,
}: {
  taskId: string;
  content: string;
  truncated?: boolean;
  resendable?: boolean;
}): ReactElement {
  const service = useService<SessionService>(SESSION_SERVICE);

  return (
    <FailedMessageResendAction
      truncated={truncated}
      resendable={resendable}
      onResend={async () => {
        await service.sendPrompt(taskId, content);
      }}
    />
  );
}
