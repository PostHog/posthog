import { useHostTRPC } from "@posthog/host-router/react";
import { Button, Switch } from "@posthog/quill";
import { ANALYTICS_EVENTS } from "@posthog/shared";
import { SUBSCRIPTION_LOGIN_ACTION } from "@posthog/ui/features/sessions/components/SubscriptionSubmenu";
import {
  applyModelAccess,
  useAdapterSubscription,
} from "@posthog/ui/features/settings/adapterSubscription";
import { SettingsCardRow } from "@posthog/ui/features/settings/components/SettingsCard";
import { useSettingsPageStore } from "@posthog/ui/features/settings/stores/settingsPageStore";
import { toast } from "@posthog/ui/primitives/toast";
import { track } from "@posthog/ui/shell/analytics";
import { openExternalUrl } from "@posthog/ui/shell/openExternal";
import { registerAdapterSubscription } from "@posthog/ui/shell/posthogAnalyticsImpl";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { type ReactElement, useEffect, useState } from "react";

const SIGN_IN_POLL_TIMEOUT_MS = 10 * 60_000 + 15_000;
const SIGN_IN_LAUNCH_FEEDBACK_MS = 4_000;

export function CodexSubscriptionSettings(): ReactElement | null {
  const subscription = useAdapterSubscription("codex");
  const hostTRPC = useHostTRPC();
  const queryClient = useQueryClient();
  const [awaitingLogin, setAwaitingLogin] = useState(false);
  const [launching, setLaunching] = useState(false);

  const statusQuery = hostTRPC.agent.codexSubscriptionStatus.queryOptions();
  const { data: status } = useQuery({
    ...statusQuery,
    enabled: subscription.flagEnabled,
    refetchInterval: (query) =>
      awaitingLogin && query.state.data?.loginState !== "logged-in"
        ? 2000
        : false,
  });
  const loggedIn = status?.loginState === "logged-in";

  useEffect(() => {
    if (!awaitingLogin || !loggedIn) return;
    setAwaitingLogin(false);
    track(ANALYTICS_EVENTS.CODEX_SUBSCRIPTION_CONNECTED);
    applyModelAccess("codex", "own-subscription", true);
    registerAdapterSubscription("codex", {
      access: "own-subscription",
      connected: true,
    });
  }, [awaitingLogin, loggedIn]);

  const login = useMutation({
    ...hostTRPC.agent.codexSubscriptionLoginStart.mutationOptions(),
    onSuccess: ({ authUrl }) => {
      openExternalUrl(authUrl);
      setAwaitingLogin(true);
      setLaunching(true);
    },
    onError: (error) =>
      toast.error("Couldn't start ChatGPT sign-in", {
        description: error.message,
      }),
  });
  useEffect(() => {
    if (!launching) return;
    const timer = setTimeout(
      () => setLaunching(false),
      SIGN_IN_LAUNCH_FEEDBACK_MS,
    );
    return () => clearTimeout(timer);
  }, [launching]);

  useEffect(() => {
    if (!awaitingLogin) return;
    const timer = setTimeout(
      () => setAwaitingLogin(false),
      SIGN_IN_POLL_TIMEOUT_MS,
    );
    return () => clearTimeout(timer);
  }, [awaitingLogin]);
  const connecting = login.isPending || launching;
  useEffect(() => {
    if (
      useSettingsPageStore.getState().initialAction ===
      SUBSCRIPTION_LOGIN_ACTION.codex
    ) {
      useSettingsPageStore.getState().consumeInitialAction();
      login.mutate();
    }
  }, [login.mutate]);

  const signOut = useMutation({
    ...hostTRPC.agent.codexSubscriptionSignOut.mutationOptions(),
    onSuccess: () => {
      track(ANALYTICS_EVENTS.CODEX_SUBSCRIPTION_SIGNED_OUT);
      applyModelAccess("codex", "posthog-gateway", false);
      registerAdapterSubscription("codex", {
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

  if (!subscription.flagEnabled) {
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
