import type { CodexCloudTerminal } from "@posthog/core/integrations/codexCloudAccountService";
import {
  Button,
  Dialog,
  DialogBody,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@posthog/quill";
import { useConnectCodexCloudAccount } from "@posthog/ui/features/settings/codexCloudAccount";
import {
  AuthTerminalPanel,
  type AuthTerminalStatus,
} from "@posthog/ui/features/settings/components/AuthTerminalPanel";
import { type ReactElement, useCallback, useState } from "react";

interface CodexCloudAuthTerminalDialogProps {
  onClose: () => void;
  sessionId: string;
  terminal: CodexCloudTerminal;
}

export function CodexCloudAuthTerminalDialog({
  onClose,
  sessionId,
  terminal,
}: CodexCloudAuthTerminalDialogProps): ReactElement {
  const connect = useConnectCodexCloudAccount();
  const [stopped, setStopped] = useState(false);
  const [connectError, setConnectError] = useState<string | null>(null);

  const connected = connect.isSuccess;

  const status = ((): AuthTerminalStatus => {
    if (connectError) return "failed";
    if (!stopped) return "running";
    if (connected) return "done";
    return "checking";
  })();

  const hint = ((): string => {
    if (connectError) return connectError;
    if (!stopped) return "Finish the login in this terminal.";
    if (connected)
      return "ChatGPT account connected. You can close this window.";
    return "Handing the login to PostHog.";
  })();

  const handleExit = useCallback(
    (code?: number) => {
      setStopped(true);
      if (code !== 0) {
        setConnectError(
          "The login did not complete. Read the output, then try again.",
        );
        return;
      }
      connect.mutate(sessionId, {
        onError: (error) => setConnectError(error.message),
      });
    },
    [connect.mutate, sessionId],
  );

  return (
    <Dialog open onOpenChange={(open) => !open && onClose()}>
      <DialogContent className="max-w-xl">
        <DialogHeader>
          <DialogTitle>Log in with ChatGPT</DialogTitle>
        </DialogHeader>
        <DialogBody className="flex flex-col gap-3">
          <p className="text-muted-foreground text-xs leading-relaxed">
            Follow the steps in this terminal. Desktop hands the login to
            PostHog when it finishes. This login is separate from your local
            codex login.
          </p>

          <AuthTerminalPanel
            sessionId={sessionId}
            commandLabel="codex login --device-auth"
            status={status}
            terminal={terminal}
            onExit={handleExit}
          />
        </DialogBody>
        <DialogFooter className="items-center justify-between gap-3">
          <span
            role={connectError ? "alert" : undefined}
            className="text-[11px] text-muted-foreground"
          >
            {hint}
          </span>
          <Button
            variant={connected ? "primary" : "outline"}
            size="sm"
            data-attr="codex-cloud-login-close"
            onClick={onClose}
          >
            {stopped ? "Close" : "Cancel"}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
