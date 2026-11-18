import type { CodexCloudTerminal } from "@posthog/core/integrations/codexCloudAccountService";
import { Button, Switch } from "@posthog/quill";
import { ANALYTICS_EVENTS } from "@posthog/shared";
import { setCloudSubscriptionOn } from "@posthog/ui/features/settings/adapterSubscription";
import {
  useCodexCloudAccount,
  useCodexCloudAccountService,
  useDisconnectCodexCloudAccount,
} from "@posthog/ui/features/settings/codexCloudAccount";
import { CodexCloudAuthTerminalDialog } from "@posthog/ui/features/settings/sections/CodexCloudAuthTerminalDialog";
import { destroyTerminalSession } from "@posthog/ui/features/terminal/destroyShellTerminal";
import { toast } from "@posthog/ui/primitives/toast";
import { track } from "@posthog/ui/shell/analytics";
import { secureRandomString } from "@posthog/ui/utils/random";
import { useMutation } from "@tanstack/react-query";
import {
  type ReactElement,
  useCallback,
  useEffect,
  useRef,
  useState,
} from "react";

interface CodexCloudSectionProps {
  cloudSubscriptionOn: boolean;
}

export function CodexCloudSection({
  cloudSubscriptionOn,
}: CodexCloudSectionProps): ReactElement {
  const account = useCodexCloudAccount();
  const disconnect = useDisconnectCodexCloudAccount();
  const service = useCodexCloudAccountService();
  const activeAttempt = useRef<string | null>(null);
  const endAttempt = useCallback((): void => {
    const id = activeAttempt.current;
    activeAttempt.current = null;
    if (!id) return;
    destroyTerminalSession(id);
    void service
      ?.cancel(id)
      .catch((error: Error) => toast.error(error.message));
  }, [service]);
  useEffect(() => endAttempt, [endAttempt]);
  const [login, setLogin] = useState<{
    id: string;
    terminal: CodexCloudTerminal;
  } | null>(null);
  const start = useMutation({
    mutationFn: async () => {
      if (!service)
        throw new Error("ChatGPT login is unavailable on this device.");
      const id = `codex-cloud-login-${secureRandomString(7)}`;
      activeAttempt.current = id;
      return { id, terminal: await service.begin(id) };
    },
    onSuccess: (result) => {
      if (activeAttempt.current === result.id) setLogin(result);
    },
    onError: (error: Error) => {
      activeAttempt.current = null;
      toast.error(error.message);
    },
  });
  const closeLogin = (): void => {
    endAttempt();
    setLogin(null);
  };
  const pending = disconnect.isPending || start.isPending;
  const status = account.data?.status ?? "not_connected";

  const disconnectAccount = (): void => {
    if (pending) return;
    disconnect.mutate(undefined, {
      onSuccess: () => {
        track(ANALYTICS_EVENTS.CODEX_CLOUD_ACCOUNT_DISCONNECTED);
        toast.success("ChatGPT account disconnected");
      },
      onError: (error) =>
        toast.error("Cannot disconnect the ChatGPT account.", {
          description: error.message,
        }),
    });
  };

  return (
    <div className="flex flex-col gap-2">
      <div className="flex items-center justify-between gap-3">
        <span className="font-medium text-xs">Cloud tasks</span>
        <Switch
          size="sm"
          aria-label="Use your ChatGPT plan for cloud tasks"
          data-attr="codex-cloud-subscription-toggle"
          checked={cloudSubscriptionOn}
          disabled={pending}
          onCheckedChange={(checked) => {
            const next = checked === true;
            if (next === cloudSubscriptionOn) return;
            setCloudSubscriptionOn("codex", next);
          }}
        />
      </div>
      <span className="text-muted-foreground text-xs">
        PostHog keeps your ChatGPT login and gives each cloud task a short-lived
        token. Tasks run when Desktop is closed. Compute is billed separately.
      </span>
      {account.isPending ? (
        <output className="text-muted-foreground text-xs">
          Checking account…
        </output>
      ) : account.isError ? (
        <span role="alert" className="text-muted-foreground text-xs">
          Cannot check the ChatGPT account. {account.error.message}
        </span>
      ) : status === "connected" ? (
        <span className="flex flex-wrap items-center gap-1.5 text-muted-foreground text-xs">
          <span
            className="inline-block h-1.5 w-1.5 shrink-0 rounded-full bg-(--green-9)"
            aria-hidden
          />
          {account.data.email
            ? `Connected as ${account.data.email}`
            : "ChatGPT account connected"}
          {account.data.plan_type ? ` (${account.data.plan_type})` : null}
          <span aria-hidden>&middot;</span>
          <button
            type="button"
            className="cursor-pointer hover:underline disabled:cursor-default"
            data-attr="codex-cloud-account-disconnect"
            disabled={pending}
            onClick={disconnectAccount}
          >
            {disconnect.isPending ? "Disconnecting…" : "Disconnect"}
          </button>
        </span>
      ) : (
        <div className="flex flex-wrap items-center justify-between gap-2 rounded-md border border-border p-3">
          <span className="text-muted-foreground text-xs">
            {status === "reauth_required"
              ? "Your ChatGPT login stopped working. Log in again to reconnect."
              : "Log in with ChatGPT. This login is separate from your local codex login."}
          </span>
          <Button
            type="button"
            variant="primary"
            size="sm"
            data-attr="codex-cloud-account-connect"
            disabled={pending}
            onClick={() => start.mutate()}
          >
            {status === "reauth_required" ? "Log in again" : "Log in"}
          </Button>
        </div>
      )}
      {login ? (
        <CodexCloudAuthTerminalDialog
          sessionId={login.id}
          terminal={login.terminal}
          onClose={closeLogin}
        />
      ) : null}
    </div>
  );
}
