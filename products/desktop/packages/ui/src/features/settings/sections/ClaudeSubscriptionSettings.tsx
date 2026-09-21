import { useHostTRPC } from "@posthog/host-router/react";
import { Button, Switch } from "@posthog/quill";
import { ANALYTICS_EVENTS } from "@posthog/shared";
import { SUBSCRIPTION_LOGIN_ACTION } from "@posthog/ui/features/sessions/components/SubscriptionSubmenu";
import { useAdapterSubscription } from "@posthog/ui/features/settings/adapterSubscription";
import { SettingsCardRow } from "@posthog/ui/features/settings/components/SettingsCard";
import { useSettingsStore } from "@posthog/ui/features/settings/settingsStore";
import { useSettingsPageStore } from "@posthog/ui/features/settings/stores/settingsPageStore";
import { track } from "@posthog/ui/shell/analytics";
import { registerAdapterSubscription } from "@posthog/ui/shell/posthogAnalyticsImpl";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { type ReactElement, useEffect, useRef, useState } from "react";
import {
  type ClaudeAuthAction,
  ClaudeAuthTerminalDialog,
} from "./ClaudeAuthTerminalDialog";
import { ClaudeCloudTokenSection } from "./ClaudeCloudTokenSection";

interface ClaudeAccountStatus {
  email?: string;
  organization?: string;
  subscriptionType?: string;
}

function connectedAccountLabel(
  status: ClaudeAccountStatus | undefined,
): string {
  if (!status?.email) return "Claude Code logged in";
  const details = [
    status.organization,
    status.subscriptionType && `${status.subscriptionType} plan`,
  ]
    .filter(Boolean)
    .join(", ");
  return details
    ? `Logged in as ${status.email} (${details})`
    : `Logged in as ${status.email}`;
}

export function ClaudeSubscriptionSettings(): ReactElement | null {
  const subscription = useAdapterSubscription("claude");
  const hostTRPC = useHostTRPC();
  const queryClient = useQueryClient();
  const [authAction, setAuthAction] = useState<ClaudeAuthAction | null>(null);

  const statusQuery = hostTRPC.agent.claudeSubscriptionStatus.queryOptions();
  const {
    data: status,
    isFetching,
    isPending,
    isError,
  } = useQuery({
    ...statusQuery,
    enabled: subscription.flagEnabled,
  });
  const loggedIn = status?.loginState === "logged-in";
  const statusUnknown = status?.loginState === "unknown";
  const settled = !isPending && !isError && !statusUnknown;

  useEffect(() => {
    if (
      useSettingsPageStore.getState().initialAction ===
      SUBSCRIPTION_LOGIN_ACTION.claude
    ) {
      useSettingsPageStore.getState().consumeInitialAction();
      setAuthAction("login");
    }
  }, []);

  const cloudSubscriptionOn = useSettingsStore(
    (state) => state.claudeCloudSubscriptionOn,
  );

  const lastKnownLoggedIn = useRef<boolean | null>(null);
  useEffect(() => {
    if (!settled) return;
    const previous = lastKnownLoggedIn.current;
    lastKnownLoggedIn.current = loggedIn;
    if (previous === null || previous === loggedIn) return;
    if (loggedIn) {
      track(ANALYTICS_EVENTS.CLAUDE_SUBSCRIPTION_CONNECTED);
    } else {
      track(ANALYTICS_EVENTS.CLAUDE_SUBSCRIPTION_SIGNED_OUT);
    }
    registerAdapterSubscription("claude", {
      access: subscription.subscriptionOn
        ? "own-subscription"
        : "posthog-gateway",
      connected: loggedIn,
    });
  }, [settled, loggedIn, subscription.subscriptionOn]);

  if (!subscription.flagEnabled && !subscription.cloudFlagEnabled) {
    return null;
  }

  const refreshStatus = (): void => {
    void queryClient.invalidateQueries({ queryKey: statusQuery.queryKey });
  };

  const statusLine = ((): { color: string; label: string } => {
    if (isPending) {
      return { color: "bg-(--gray-9)", label: "Checking" };
    }
    if (isError || statusUnknown) {
      return { color: "bg-(--amber-9)", label: "Could not check the login" };
    }
    if (loggedIn) {
      return { color: "bg-(--green-9)", label: connectedAccountLabel(status) };
    }
    return { color: "bg-(--red-9)", label: "Not logged in" };
  })();

  return (
    <SettingsCardRow
      stacked
      label="Claude subscription"
      description="Choose where to use your Claude plan. Model use counts toward your plan limits."
    >
      <div className="flex flex-col gap-5 pt-2">
        {subscription.flagEnabled ? (
          <div className="flex flex-col gap-2">
            <div className="flex items-center justify-between gap-3">
              <span className="font-medium text-xs">Local tasks</span>
              <Switch
                size="sm"
                aria-label="Use your Claude plan for local tasks"
                checked={subscription.subscriptionOn}
                onCheckedChange={(checked) => {
                  subscription.setSubscriptionOn(checked === true);
                  refreshStatus();
                }}
              />
            </div>
            <span className="text-muted-foreground text-xs">
              Use your Claude Code login for local and worktree tasks.
            </span>
            <div className="flex flex-wrap items-center justify-between gap-2">
              <span className="flex min-w-0 items-center gap-1.5 text-muted-foreground text-xs">
                <span
                  className={`inline-block h-1.5 w-1.5 shrink-0 rounded-full ${statusLine.color}`}
                  aria-hidden
                />
                <span className="break-words">{statusLine.label}</span>
              </span>
              <div className="flex items-center gap-2">
                <Button
                  variant={loggedIn ? "outline" : "primary"}
                  size="sm"
                  disabled={isPending}
                  onClick={() => setAuthAction(loggedIn ? "logout" : "login")}
                >
                  {loggedIn ? "Log out" : "Log in"}
                </Button>
                <Button
                  variant="outline"
                  size="sm"
                  loading={isFetching}
                  disabled={isFetching}
                  onClick={refreshStatus}
                >
                  Re-check
                </Button>
              </div>
            </div>
          </div>
        ) : null}
        {subscription.cloudFlagEnabled ? (
          <ClaudeCloudTokenSection
            cloudSubscriptionOn={cloudSubscriptionOn}
            onCreateToken={() => setAuthAction("setup-token")}
          />
        ) : null}
      </div>
      {authAction ? (
        <ClaudeAuthTerminalDialog
          action={authAction}
          onClose={() => setAuthAction(null)}
          onFinished={refreshStatus}
        />
      ) : null}
    </SettingsCardRow>
  );
}
