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
import { destroyTerminalSession } from "@posthog/ui/features/terminal/destroyShellTerminal";
import { Terminal } from "@posthog/ui/features/terminal/Terminal";
import { useThemeStore } from "@posthog/ui/shell/themeStore";
import { secureRandomString } from "@posthog/ui/utils/random";
import { useQuery } from "@tanstack/react-query";
import { type ReactElement, useCallback, useEffect, useState } from "react";

export type ClaudeAuthAction = "login" | "logout";

interface ClaudeAuthTerminalDialogProps {
  action: ClaudeAuthAction;
  onClose: () => void;
  onFinished: () => void;
}

const SURFACE = {
  dark: { body: "#131316", chrome: "#1c1c21", text: "#e6e6e6" },
  light: { body: "#f2f3ee", chrome: "#e7e9e1", text: "#3a4036" },
} as const;

const COPY = {
  login: {
    title: "Log in to Claude Code",
    lead: "The CLI opens your browser. If it asks for a code, paste the code in the terminal.",
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

type Status = "running" | "checking" | "done" | "failed";

const PILL: Record<Status, { dot: string; label: string }> = {
  running: {
    dot: "animate-pulse bg-(--amber-9) motion-reduce:animate-none",
    label: "Running",
  },
  checking: {
    dot: "animate-pulse bg-(--gray-9) motion-reduce:animate-none",
    label: "Checking",
  },
  done: { dot: "bg-(--green-9)", label: "Done" },
  failed: { dot: "bg-(--red-9)", label: "Failed" },
};

export function ClaudeAuthTerminalDialog({
  action,
  onClose,
  onFinished,
}: ClaudeAuthTerminalDialogProps): ReactElement {
  const hostTRPC = useHostTRPC();
  const isDarkMode = useThemeStore((state) => state.isDarkMode);
  const [started, setStarted] = useState(action === "login");
  const { data: terminal } = useQuery({
    ...hostTRPC.agent.claudeAuthTerminal.queryOptions({ action }),
    enabled: started,
  });
  const [sessionId] = useState(
    () => `claude-auth-${action}-${secureRandomString(7)}`,
  );
  const [stopped, setStopped] = useState(false);

  const statusQuery = useQuery({
    ...hostTRPC.agent.claudeSubscriptionStatus.queryOptions(),
    enabled: stopped,
  });
  const loggedIn = statusQuery.data?.loginState === "logged-in";
  const statusKnown = statusQuery.data?.loginState !== undefined;
  const verified = ((): boolean | undefined => {
    if (!stopped || statusQuery.isFetching || !statusKnown) {
      return undefined;
    }
    return action === "login" ? loggedIn : !loggedIn;
  })();

  const copy = COPY[action];
  const surface = isDarkMode ? SURFACE.dark : SURFACE.light;

  const status = ((): Status => {
    if (!stopped) return "running";
    if (verified === undefined) return "checking";
    return verified ? "done" : "failed";
  })();

  const hint = ((): string => {
    if (!started) return "Nothing changes until you select Log out.";
    if (status === "running") return "The command runs. Close to stop it.";
    if (status === "checking") return "Reading the login status.";
    return verified ? copy.ok : copy.failed;
  })();

  const handleExit = useCallback(() => {
    setStopped(true);
    onFinished();
  }, [onFinished]);

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
          <p className="text-(--gray-11) text-xs leading-relaxed">
            {copy.lead}
          </p>

          {started && terminal ? (
            <div
              className="overflow-hidden rounded-(--radius-3) border border-(--gray-6) shadow-sm"
              style={{ backgroundColor: surface.body, color: surface.text }}
            >
              <div
                className="flex items-center justify-between border-black/10 border-b px-3 py-1.5"
                style={{ backgroundColor: surface.chrome }}
              >
                <span className="flex items-center gap-2 font-mono text-[11px] opacity-80">
                  <span aria-hidden>❯</span>
                  {copy.command}
                </span>
                <span className="flex items-center gap-1.5 font-mono text-[10px] uppercase tracking-wide opacity-70">
                  <span
                    className={`inline-block h-1.5 w-1.5 rounded-full ${PILL[status].dot}`}
                    aria-hidden
                  />
                  {PILL[status].label}
                </span>
              </div>
              <div className="h-44">
                <Terminal
                  sessionId={sessionId}
                  persistenceKey={sessionId}
                  cwd={terminal.cwd}
                  command={terminal.command}
                  additionalEnv={terminal.additionalEnv}
                  unsetEnv={terminal.unsetEnv}
                  sensitive
                  onExit={handleExit}
                />
              </div>
            </div>
          ) : null}
        </DialogBody>
        <DialogFooter className="items-center justify-between gap-3">
          <span className="text-(--gray-10) text-[11px]">{hint}</span>
          {started ? (
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
