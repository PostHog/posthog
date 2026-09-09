import { useHostTRPC } from "@posthog/host-router/react";
import { Button, Switch } from "@posthog/quill";
import { ANALYTICS_EVENTS } from "@posthog/shared";
import { setCloudSubscriptionOn } from "@posthog/ui/features/settings/adapterSubscription";
import { toast } from "@posthog/ui/primitives/toast";
import { track } from "@posthog/ui/shell/analytics";
import { openExternalUrl } from "@posthog/ui/shell/openExternal";
import { useMutation, useQuery } from "@tanstack/react-query";
import { type ReactElement, useEffect, useState } from "react";

/** OpenAI expires a device code after 15 minutes. */
const DEVICE_CODE_TIMEOUT_MS = 15 * 60_000;

interface CodexCloudSectionProps {
  cloudSubscriptionOn: boolean;
  onConnected: () => void;
}

function planWindowLabel(window: {
  usedPercent: number;
  windowDurationMins?: number;
  resetsAt?: string;
}): string {
  const left = Math.max(0, Math.round(100 - window.usedPercent));
  const hours = window.windowDurationMins
    ? Math.round(window.windowDurationMins / 60)
    : undefined;
  return hours ? `${left}% left in this ${hours}h window` : `${left}% left`;
}

export function CodexCloudSection({
  cloudSubscriptionOn,
  onConnected,
}: CodexCloudSectionProps): ReactElement {
  const hostTRPC = useHostTRPC();
  const [awaitingLogin, setAwaitingLogin] = useState(false);
  const [copied, setCopied] = useState(false);

  // A second observer of the shared status query: while the user is entering
  // the code, this one polls, and both cards settle together.
  const { data: status } = useQuery({
    ...hostTRPC.agent.codexSubscriptionStatus.queryOptions(),
    refetchInterval: (query) =>
      awaitingLogin && query.state.data?.loginState !== "logged-in"
        ? 2_000
        : false,
  });
  const connected = status?.loginState === "logged-in";

  const rateLimitsQuery = hostTRPC.agent.codexRateLimits.queryOptions();
  const { data: rateLimits } = useQuery({
    ...rateLimitsQuery,
    enabled: connected && cloudSubscriptionOn,
    staleTime: 60_000,
  });

  const deviceLogin = useMutation({
    ...hostTRPC.agent.codexSubscriptionDeviceLoginStart.mutationOptions(),
    onSuccess: () => {
      setAwaitingLogin(true);
      track(ANALYTICS_EVENTS.CODEX_CLOUD_DEVICE_LOGIN_STARTED);
    },
    onError: (error) =>
      toast.error("Couldn't start the code sign-in", {
        description: error.message.includes("device code login is not enabled")
          ? "Turn on device code login in your ChatGPT security settings. In a workspace, an admin must turn it on."
          : error.message,
      }),
  });

  useEffect(() => {
    if (!awaitingLogin) return;
    const timer = setTimeout(
      () => setAwaitingLogin(false),
      DEVICE_CODE_TIMEOUT_MS,
    );
    return () => clearTimeout(timer);
  }, [awaitingLogin]);

  useEffect(() => {
    if (!awaitingLogin || !connected) return;
    setAwaitingLogin(false);
    onConnected();
  }, [awaitingLogin, connected, onConnected]);

  const code = awaitingLogin ? deviceLogin.data?.userCode : undefined;
  const verificationUrl = deviceLogin.data?.verificationUrl;

  const copyCode = async (): Promise<void> => {
    if (!code) return;
    await navigator.clipboard.writeText(code);
    setCopied(true);
    setTimeout(() => setCopied(false), 2_000);
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
          onCheckedChange={(checked) =>
            setCloudSubscriptionOn("codex", checked === true)
          }
        />
      </div>
      <span className="text-muted-foreground text-xs">
        Keep Desktop open for the whole task. Compute is billed separately.
      </span>
      {connected ? (
        <span className="text-muted-foreground text-xs">
          {rateLimits?.primary
            ? `Plan allowance: ${planWindowLabel(rateLimits.primary)}`
            : "Cloud tasks share the allowance your local tasks use."}
        </span>
      ) : code && verificationUrl ? (
        <div className="flex flex-col gap-3 rounded-md border border-border p-3">
          <span className="text-muted-foreground text-xs">
            Open the sign-in page and enter this code.
          </span>
          <div className="flex flex-wrap items-center gap-2">
            <code className="rounded-(--radius-2) bg-(--gray-3) px-2 py-1 font-mono text-sm tracking-widest">
              {code}
            </code>
            <Button
              type="button"
              variant="outline"
              size="sm"
              onClick={() => void copyCode()}
            >
              {copied ? "Copied" : "Copy code"}
            </Button>
            <Button
              type="button"
              variant="primary"
              size="sm"
              onClick={() => openExternalUrl(verificationUrl)}
            >
              Open sign-in page
            </Button>
          </div>
          <span className="text-muted-foreground text-xs">
            The code stops working after 15 minutes. This card updates when you
            finish.
          </span>
        </div>
      ) : (
        <div className="flex flex-wrap items-center justify-between gap-2 rounded-md border border-border p-3">
          <span className="text-muted-foreground text-xs">
            Connect your ChatGPT account to run cloud tasks on your plan.
          </span>
          <Button
            type="button"
            variant="outline"
            size="sm"
            data-attr="codex-cloud-device-login"
            loading={deviceLogin.isPending}
            disabled={deviceLogin.isPending}
            onClick={() => deviceLogin.mutate()}
          >
            Connect with a code
          </Button>
        </div>
      )}
    </div>
  );
}
