import { useHostTRPC } from "@posthog/host-router/react";
import {
  Button,
  Dialog,
  DialogBody,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@posthog/quill";
import { findClaudeSetupToken } from "@posthog/ui/features/settings/claudeCloudToken";
import {
  AuthTerminalPanel,
  type AuthTerminalStatus,
} from "@posthog/ui/features/settings/components/AuthTerminalPanel";
import { destroyTerminalSession } from "@posthog/ui/features/terminal/destroyShellTerminal";
import { secureRandomString } from "@posthog/ui/utils/random";
import { useQuery } from "@tanstack/react-query";
import {
  type ReactElement,
  useCallback,
  useEffect,
  useRef,
  useState,
} from "react";

export type ClaudeAuthAction = "login" | "logout" | "setup-token";

interface ClaudeAuthTerminalDialogProps {
  action: ClaudeAuthAction;
  onClose: () => void;
  onFinished?: () => void;
  onSaveToken?: (token: string) => void;
  savingToken?: boolean;
}

const MAX_OUTPUT_CHARS = 64 * 1024;
const SETUP_TOKEN_SAVE_LEAD =
  "Follow the steps in this terminal. Desktop reads the token when the command ends.";
const SETUP_TOKEN_FOUND =
  "Desktop found a new Claude token. Save it for your cloud tasks?";

const COPY = {
  "setup-token": {
    title: "Create a Claude token",
    lead: "Follow the steps in this terminal. Copy the token. Close this window, then paste the token into Cloud tasks.",
    command: "claude setup-token",
    ok: "Copy the token. Close this window, then paste the token into Cloud tasks.",
    failed:
      "Token setup did not finish. Read the terminal output, then try again.",
  },
  login: {
    title: "Log in to Claude Code",
    lead: "Claude opens your browser. If it asks for a code, paste it in this terminal.",
    command: "claude auth login",
    ok: "Claude Code is logged in. You can close this window.",
    failed: "The login did not complete. Read the output, then try again.",
  },
  logout: {
    title: "Log out of Claude Code",
    lead: "This signs out the Claude Code CLI on this machine. Sessions on your Claude subscription stop until you log in again.",
    command: "claude auth logout",
    ok: "Claude Code is logged out. You can close this window.",
    failed: "The sign-out did not complete. Read the output, then try again.",
  },
} as const;

export function ClaudeAuthTerminalDialog({
  action,
  onClose,
  onFinished,
  onSaveToken,
  savingToken = false,
}: ClaudeAuthTerminalDialogProps): ReactElement {
  const hostTRPC = useHostTRPC();
  const [started, setStarted] = useState(action !== "logout");
  const {
    data: terminal,
    isPending: terminalPending,
    isError: terminalError,
  } = useQuery({
    ...hostTRPC.agent.claudeAuthTerminal.queryOptions({ action }),
    enabled: started,
  });
  const [sessionId] = useState(
    () => `claude-auth-${action}-${secureRandomString(7)}`,
  );
  const [stopped, setStopped] = useState(false);
  const [exitCode, setExitCode] = useState<number | undefined>();
  const readsToken = action === "setup-token" && !!onSaveToken;
  const outputRef = useRef("");
  const [foundToken, setFoundToken] = useState<string | null>(null);

  const statusQuery = useQuery({
    ...hostTRPC.agent.claudeSubscriptionStatus.queryOptions(),
    enabled: stopped && action !== "setup-token",
  });
  const loggedIn = statusQuery.data?.loginState === "logged-in";
  const statusKnown = statusQuery.data?.loginState !== undefined;
  const verified = ((): boolean | undefined => {
    if (action === "setup-token") return stopped ? exitCode === 0 : undefined;
    if (statusQuery.isError) return false;
    if (!stopped || statusQuery.isFetching || !statusKnown) {
      return undefined;
    }
    return action === "login"
      ? loggedIn
      : statusQuery.data?.loginState === "logged-out";
  })();

  const copy = COPY[action];
  const lead = readsToken ? SETUP_TOKEN_SAVE_LEAD : copy.lead;

  const status = ((): AuthTerminalStatus => {
    if (terminalError) return "failed";
    if (!stopped) return "running";
    if (verified === undefined) return "checking";
    return verified ? "done" : "failed";
  })();

  const offersSave = readsToken && status === "done" && foundToken !== null;

  const hint = ((): string => {
    if (!started) return "Nothing changes until you select Log out.";
    if (terminalError)
      return "Could not open the terminal. Close this window and try again.";
    if (terminalPending) return "Opening the terminal.";
    if (status === "running") return "The command runs. Close to stop it.";
    if (status === "checking") return "Reading the login status.";
    if (offersSave) return SETUP_TOKEN_FOUND;
    return verified ? copy.ok : copy.failed;
  })();

  const handleExit = useCallback(
    (code?: number) => {
      setExitCode(code);
      setStopped(true);
      onFinished?.();
    },
    [onFinished],
  );

  const handleOutput = useCallback((data: string) => {
    outputRef.current = (outputRef.current + data).slice(-MAX_OUTPUT_CHARS);
    setFoundToken(findClaudeSetupToken(outputRef.current));
  }, []);

  const handleClose = useCallback(() => {
    destroyTerminalSession(sessionId);
    onClose();
  }, [sessionId, onClose]);

  useEffect(() => {
    return () => {
      destroyTerminalSession(sessionId);
    };
  }, [sessionId]);

  return (
    <Dialog open onOpenChange={(open) => !open && handleClose()}>
      <DialogContent className="max-w-xl">
        <DialogHeader>
          <DialogTitle>{copy.title}</DialogTitle>
        </DialogHeader>
        <DialogBody className="flex flex-col gap-3">
          <p className="text-(--gray-11) text-xs leading-relaxed">{lead}</p>

          {started && terminalPending ? (
            <output className="text-muted-foreground text-xs">
              Opening the terminal…
            </output>
          ) : null}
          {started && terminalError ? (
            <span role="alert" className="text-xs">
              Could not open the terminal. Close this window and try again.
            </span>
          ) : null}
          {started && terminal ? (
            <AuthTerminalPanel
              sessionId={sessionId}
              commandLabel={copy.command}
              status={status}
              terminal={terminal}
              onExit={handleExit}
              onOutput={readsToken ? handleOutput : undefined}
            />
          ) : null}
        </DialogBody>
        <DialogFooter className="items-center justify-between gap-3">
          <span className="text-(--gray-10) text-[11px]">{hint}</span>
          {offersSave ? (
            <span className="flex items-center gap-2">
              <Button
                variant="outline"
                size="sm"
                disabled={savingToken}
                onClick={handleClose}
              >
                Cancel
              </Button>
              <Button
                variant="primary"
                size="sm"
                loading={savingToken}
                disabled={savingToken}
                data-attr="claude-cloud-token-save-found"
                onClick={() => {
                  if (foundToken && !savingToken) onSaveToken?.(foundToken);
                }}
              >
                Save token
              </Button>
            </span>
          ) : started ? (
            <Button
              variant={status === "done" ? "primary" : "outline"}
              size="sm"
              onClick={handleClose}
            >
              {status === "running" ? "Cancel" : "Close"}
            </Button>
          ) : (
            <span className="flex items-center gap-2">
              <Button variant="outline" size="sm" onClick={handleClose}>
                Keep me logged in
              </Button>
              <Button
                variant="primary"
                size="sm"
                onClick={() => setStarted(true)}
              >
                Log out
              </Button>
            </span>
          )}
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
