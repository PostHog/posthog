import { useHostTRPC } from "@posthog/host-router/react";
import { Button, Switch } from "@posthog/quill";
import { ANALYTICS_EVENTS } from "@posthog/shared";
import { SettingsCardRow } from "@posthog/ui/features/settings/components/SettingsCard";
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
    applyCodexModelAccess("own-subscription", true);
    registerCodexSubscription({ access: "own-subscription", connected: true });
  }, [awaitingLogin, loggedIn]);

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

  if (!loggedIn) {
    return (
      <SettingsCardRow
        label="ChatGPT account"
        description={
          awaitingLogin
            ? "Finish signing in with your browser. This updates automatically"
            : "Connect to run local and worktree Codex sessions on your ChatGPT plan"
        }
      >
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
      </SettingsCardRow>
    );
  }

  return (
    <SettingsCardRow
      label="Use your ChatGPT subscription"
      description={
        <span className="flex flex-col gap-1">
          <span>
            Local and worktree Codex sessions run on your ChatGPT plan instead
            of PostHog credits. Cloud tasks always use PostHog credits
          </span>
          <span className="flex items-center gap-1.5">
            <span
              className="inline-block h-1.5 w-1.5 rounded-full bg-(--green-9)"
              aria-hidden
            />
            ChatGPT account connected
            <span aria-hidden>&middot;</span>
            <button
              type="button"
              className="cursor-pointer hover:underline"
              disabled={signOut.isPending}
              onClick={() => signOut.mutate()}
            >
              Sign out
            </button>
          </span>
        </span>
      }
    >
      <Switch
        size="sm"
        checked={subscription.subscriptionOn}
        onCheckedChange={(checked) =>
          subscription.setSubscriptionOn(checked === true)
        }
      />
    </SettingsCardRow>
  );
}
