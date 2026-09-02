import { useHostTRPC } from "@posthog/host-router/react";
import { Button, Switch } from "@posthog/quill";
import { ANALYTICS_EVENTS } from "@posthog/shared";
import { SUBSCRIPTION_LOGIN_ACTION } from "@posthog/ui/features/sessions/components/SubscriptionSubmenu";
import { useAdapterSubscription } from "@posthog/ui/features/settings/adapterSubscription";
import { SettingsCardRow } from "@posthog/ui/features/settings/components/SettingsCard";
import { useSettingsPageStore } from "@posthog/ui/features/settings/stores/settingsPageStore";
import { track } from "@posthog/ui/shell/analytics";
import { registerAdapterSubscription } from "@posthog/ui/shell/posthogAnalyticsImpl";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { type ReactElement, useEffect, useRef, useState } from "react";
import {
  type ClaudeAuthAction,
  ClaudeAuthTerminalDialog,
} from "./ClaudeAuthTerminalDialog";

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

  if (!subscription.flagEnabled) {
    return null;
  }

  const refreshStatus = (): void => {
    void queryClient.invalidateQueries({ queryKey: statusQuery.queryKey });
  };

  const usingSubscription = loggedIn && subscription.subscriptionOn;
  const summary = usingSubscription
    ? "Local and worktree Claude sessions run on your Claude plan instead of PostHog credits. Cloud tasks always use PostHog credits"
    : loggedIn
      ? "Your Claude account is connected, but the switch is off. Local and worktree Claude sessions still use PostHog credits. Turn the switch on to use your Claude plan"
      : "Run local and worktree Claude sessions on your Claude plan instead of PostHog credits. Log in once with the Claude Code CLI, then re-check";

  const statusLine = ((): { color: string; label: string } => {
    if (isPending) {
      return { color: "bg-(--gray-9)", label: "Checking" };
    }
    if (isError || statusUnknown) {
      return { color: "bg-(--amber-9)", label: "Could not check the login" };
    }
    if (loggedIn) {
      return { color: "bg-(--green-9)", label: "Claude Code logged in" };
    }
    return { color: "bg-(--red-9)", label: "Not logged in" };
  })();

  const description = (
    <span className="flex flex-col gap-1">
      <span>{summary}</span>
      <span className="flex items-center gap-1.5">
        <span
          className={`inline-block h-1.5 w-1.5 rounded-full ${statusLine.color}`}
          aria-hidden
        />
        {statusLine.label}
      </span>
      {!loggedIn && settled ? (
        <span className="text-[11px] text-muted-foreground">
          Log in here, or run claude in a terminal and use /login
        </span>
      ) : null}
    </span>
  );

  return (
    <SettingsCardRow
      label="Use your Claude subscription"
      description={description}
    >
      <span className="flex flex-wrap items-center justify-end gap-2">
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
        <Switch
          size="sm"
          aria-label="Use your Claude subscription"
          checked={subscription.subscriptionOn}
          onCheckedChange={(checked) => {
            subscription.setSubscriptionOn(checked === true);
            refreshStatus();
          }}
        />
      </span>
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
