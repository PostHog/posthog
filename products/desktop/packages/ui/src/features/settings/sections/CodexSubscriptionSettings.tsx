import { useHostTRPC } from "@posthog/host-router/react";
import { Button, Switch } from "@posthog/quill";
import { ANALYTICS_EVENTS } from "@posthog/shared";
import { SettingsCardRow } from "@posthog/ui/features/settings/components/SettingsCard";
import { useSettingsStore } from "@posthog/ui/features/settings/settingsStore";
import {
  applyCodexModelAccess,
  shouldShowCodexSubscriptionControls,
  useCodexSubscription,
} from "@posthog/ui/features/settings/useCodexSubscription";
import { track } from "@posthog/ui/shell/analytics";
import { openExternalUrl } from "@posthog/ui/shell/openExternal";
import { registerCodexSubscription } from "@posthog/ui/shell/posthogAnalyticsImpl";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";

// Detection is existence-only and sign-in runs through Codex's own login flow
// into an app-private CODEX_HOME; the user's ~/.codex credentials are never read.
export function CodexSubscriptionSettings() {
  const subscription = useCodexSubscription();
  const codexModelAccess = useSettingsStore((s) => s.codexModelAccess);
  const hostTRPC = useHostTRPC();
  const queryClient = useQueryClient();
  const [awaitingLogin, setAwaitingLogin] = useState(false);

  const statusQuery = hostTRPC.agent.codexSubscriptionStatus.queryOptions();
  const { data: status } = useQuery({
    ...statusQuery,
    enabled: subscription.flagEnabled,
    refetchInterval: (query) =>
      awaitingLogin && query.state.data?.appLoggedIn !== true ? 2000 : false,
  });
  const loggedIn = status?.appLoggedIn === true;

  useEffect(() => {
    if (!awaitingLogin || !loggedIn) return;
    setAwaitingLogin(false);
    track(ANALYTICS_EVENTS.CODEX_SUBSCRIPTION_CONNECTED);
    registerCodexSubscription({ access: codexModelAccess, connected: true });
  }, [awaitingLogin, loggedIn, codexModelAccess]);

  const login = useMutation({
    ...hostTRPC.agent.codexSubscriptionLoginStart.mutationOptions(),
    onSuccess: ({ authUrl }) => {
      openExternalUrl(authUrl);
      setAwaitingLogin(true);
    },
  });
  const signOut = useMutation({
    ...hostTRPC.agent.codexSubscriptionSignOut.mutationOptions(),
    onSuccess: () => {
      track(ANALYTICS_EVENTS.CODEX_SUBSCRIPTION_SIGNED_OUT);
      applyCodexModelAccess("posthog-gateway", false);
      registerCodexSubscription({
        access: "posthog-gateway",
        connected: false,
      });
    },
    onSettled: () => {
      setAwaitingLogin(false);
      void queryClient.invalidateQueries({ queryKey: statusQuery.queryKey });
    },
  });

  const visible = shouldShowCodexSubscriptionControls({
    flagEnabled: subscription.flagEnabled,
    adapter: "codex",
    status,
    subscriptionOn: subscription.subscriptionOn,
  });
  if (!visible) {
    return null;
  }

  return (
    <SettingsCardRow
      label="Use your ChatGPT subscription"
      description="Local and worktree Codex sessions run on your ChatGPT plan instead of PostHog credits. Cloud tasks always use PostHog credits"
    >
      <div className="flex flex-col items-end gap-2">
        <Switch
          size="sm"
          checked={subscription.subscriptionOn}
          disabled={!loggedIn && !subscription.subscriptionOn}
          onCheckedChange={(checked) =>
            subscription.setSubscriptionOn(checked === true)
          }
        />
        {!loggedIn && (
          <div className="flex flex-col items-end gap-1">
            <Button
              variant="outline"
              size="sm"
              disabled={login.isPending}
              onClick={() => login.mutate()}
            >
              {login.isPending
                ? "Opening browser..."
                : awaitingLogin
                  ? "Try again"
                  : "Connect ChatGPT account"}
            </Button>
            <span className="text-right text-(--gray-11) text-[12px]">
              {awaitingLogin
                ? "Finish signing in with your browser. This updates automatically"
                : "Connect your ChatGPT account before you turn this on"}
            </span>
          </div>
        )}
        {loggedIn && (
          <div className="flex items-center gap-2">
            <span className="text-(--gray-11) text-[12px]">
              ChatGPT account connected
            </span>
            <Button
              variant="outline"
              size="sm"
              disabled={signOut.isPending}
              onClick={() => signOut.mutate()}
            >
              Sign out
            </Button>
          </div>
        )}
      </div>
    </SettingsCardRow>
  );
}
