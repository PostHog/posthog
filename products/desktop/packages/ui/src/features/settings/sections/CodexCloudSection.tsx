import { Button, Switch } from "@posthog/quill";
import { ANALYTICS_EVENTS } from "@posthog/shared";
import { setCloudSubscriptionOn } from "@posthog/ui/features/settings/adapterSubscription";
import {
  CODEX_CLOUD_LOGIN_COMMAND,
  useCodexCloudAccount,
  useConnectCodexCloudAccount,
  useDisconnectCodexCloudAccount,
} from "@posthog/ui/features/settings/codexCloudAccount";
import { toast } from "@posthog/ui/primitives/toast";
import { track } from "@posthog/ui/shell/analytics";
import { type ReactElement, useState } from "react";

interface CodexCloudSectionProps {
  cloudSubscriptionOn: boolean;
}

export function CodexCloudSection({
  cloudSubscriptionOn,
}: CodexCloudSectionProps): ReactElement {
  const account = useCodexCloudAccount();
  const connect = useConnectCodexCloudAccount();
  const disconnect = useDisconnectCodexCloudAccount();
  const [copied, setCopied] = useState(false);
  const pending = connect.isPending || disconnect.isPending;
  const status = account.data?.status ?? "not_connected";

  const copyCommand = async (): Promise<void> => {
    await navigator.clipboard.writeText(CODEX_CLOUD_LOGIN_COMMAND);
    setCopied(true);
    setTimeout(() => setCopied(false), 2_000);
  };

  const connectAccount = (): void => {
    if (pending) return;
    connect.mutate(undefined, {
      onSuccess: () => {
        track(ANALYTICS_EVENTS.CODEX_CLOUD_ACCOUNT_CONNECTED);
        toast.success("ChatGPT account connected");
      },
      onError: (error) =>
        toast.error("Cannot connect the ChatGPT account.", {
          description: error.message,
        }),
    });
  };

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
        <div className="flex flex-col gap-3 rounded-md border border-border p-3">
          <span className="text-muted-foreground text-xs">
            {status === "reauth_required"
              ? "Your ChatGPT login stopped working. Log in again, then connect the account again."
              : "Log in with ChatGPT in a terminal, then connect the account. This login is separate from your local codex login."}
          </span>
          <div className="flex flex-wrap items-center gap-2">
            <code className="min-w-0 break-all rounded-(--radius-2) bg-(--gray-3) px-2 py-1 font-mono text-xs">
              {CODEX_CLOUD_LOGIN_COMMAND}
            </code>
            <Button
              type="button"
              variant="outline"
              size="sm"
              data-attr="codex-cloud-login-command-copy"
              onClick={() => void copyCommand()}
            >
              {copied ? "Copied" : "Copy command"}
            </Button>
          </div>
          <div className="flex flex-wrap items-center justify-between gap-2">
            <span className="text-muted-foreground text-xs">
              Desktop reads the login file the command writes and hands it to
              PostHog. The file is deleted after that.
            </span>
            <Button
              type="button"
              variant="primary"
              size="sm"
              data-attr="codex-cloud-account-connect"
              loading={connect.isPending}
              disabled={pending}
              onClick={connectAccount}
            >
              Connect
            </Button>
          </div>
        </div>
      )}
    </div>
  );
}
