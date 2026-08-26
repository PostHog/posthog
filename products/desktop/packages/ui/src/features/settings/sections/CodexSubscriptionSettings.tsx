import { useHostTRPC } from "@posthog/host-router/react";
import { Button, Switch } from "@posthog/quill";
import { ANALYTICS_EVENTS } from "@posthog/shared";
import { SettingsCardRow } from "@posthog/ui/features/settings/components/SettingsCard";
import {
  applyCodexModelAccess,
  shouldShowCodexSubscriptionControls,
  useCodexSubscription,
} from "@posthog/ui/features/settings/useCodexSubscription";
import { toast } from "@posthog/ui/primitives/toast";
import { track } from "@posthog/ui/shell/analytics";
import { openExternalUrl } from "@posthog/ui/shell/openExternal";
import { registerCodexSubscription } from "@posthog/ui/shell/posthogAnalyticsImpl";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";

// The codex login host self-terminates ~10 minutes after sign-in starts (see
// LOGIN_TIMEOUT_MS in the subscription-login adapter). Once it is gone, finishing
// in the browser can no longer land. Give the poll a small grace past that
// deadline so a last-moment success still lands, then stop it instead of polling
// for the settings page's whole mounted life.
const LOGIN_POLL_TIMEOUT_MS = 10 * 60 * 1000 + 15 * 1000;

// Sign-in uses Codex's own login flow. The app never reads ~/.codex credentials.
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
      setLaunching(true);
    },
    // Without this a failed spawn/handshake is silent: the button just reverts
    // to "Connect ChatGPT account" and reads as broken. Leave it clickable.
    onError: (error) =>
      toast.error("Couldn't start ChatGPT sign-in", {
        description: error.message,
      }),
  });
  const [launching, setLaunching] = useState(false);
  useEffect(() => {
    if (!launching) return;
    const timer = setTimeout(() => setLaunching(false), 4000);
    return () => clearTimeout(timer);
  }, [launching]);

  // Bound the sign-in poll. If the user never finishes, the backend host dies at
  // its own deadline and cannot report back, so drop the waiting state. That
  // stops the poll and reverts the card to "Connect ChatGPT account" instead of
  // showing an active sign-in forever.
  useEffect(() => {
    if (!awaitingLogin) return;
    const timer = setTimeout(
      () => setAwaitingLogin(false),
      LOGIN_POLL_TIMEOUT_MS,
    );
    return () => clearTimeout(timer);
  }, [awaitingLogin]);
  const connecting = login.isPending || launching;
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
    onError: (error) =>
      toast.error("Couldn't sign out of ChatGPT", {
        description: error.message,
      }),
    onSettled: () => {
      setAwaitingLogin(false);
      void queryClient.invalidateQueries({ queryKey: statusQuery.queryKey });
    },
  });

  const visible = shouldShowCodexSubscriptionControls({
    flagEnabled: subscription.flagEnabled,
    adapter: "codex",
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
          loading={connecting}
          disabled={connecting}
          onClick={() => login.mutate()}
        >
          {connecting
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
