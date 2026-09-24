import { useHostTRPC } from "@posthog/host-router/react";
import { Button } from "@posthog/quill";
import { ANALYTICS_EVENTS, PI_SUBSCRIPTION_PROVIDER } from "@posthog/shared";
import { SettingsCardRow } from "@posthog/ui/features/settings/components/SettingsCard";
import { usePiSubscription } from "@posthog/ui/features/settings/piSubscription";
import { toast } from "@posthog/ui/primitives/toast";
import { track } from "@posthog/ui/shell/analytics";
import { openExternalUrl } from "@posthog/ui/shell/openExternal";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { type ReactElement, useEffect, useRef, useState } from "react";

const SIGN_IN_POLL_TIMEOUT_MS = 10 * 60_000 + 15_000;
const CHATGPT_SUBSCRIPTION_SUMMARY =
  "Local and worktree Pi sessions use your ChatGPT plan instead of PostHog credits. Cloud tasks use PostHog credits";

export function PiSubscriptionSettings(): ReactElement | null {
  const { flagEnabled } = usePiSubscription();
  const hostTRPC = useHostTRPC();
  const queryClient = useQueryClient();
  const [pendingAuthUrl, setPendingAuthUrl] = useState<string | null>(null);

  const statusQuery = hostTRPC.agent.piSubscriptionStatus.queryOptions();
  const { data: status, isLoading: statusLoading } = useQuery({
    ...statusQuery,
    refetchInterval: (query) =>
      pendingAuthUrl && query.state.data?.loginState !== "logged-in"
        ? 2000
        : false,
  });
  const loggedIn = status?.loginState === "logged-in";

  useEffect(() => {
    if (!pendingAuthUrl || !loggedIn) {
      return;
    }
    setPendingAuthUrl(null);
    track(ANALYTICS_EVENTS.PI_SUBSCRIPTION_CONNECTED, {
      provider: PI_SUBSCRIPTION_PROVIDER,
    });
  }, [pendingAuthUrl, loggedIn]);

  const login = useMutation({
    ...hostTRPC.agent.piSubscriptionLoginStart.mutationOptions(),
    onSuccess: ({ authUrl }) => {
      setPendingAuthUrl(authUrl);
      openExternalUrl(authUrl);
    },
    onError: (error) =>
      toast.error("Couldn't start ChatGPT sign-in", {
        description: error.message,
      }),
  });

  const cancel = useMutation({
    ...hostTRPC.agent.piSubscriptionLoginCancel.mutationOptions(),
    onSettled: () => {
      setPendingAuthUrl(null);
      void queryClient.invalidateQueries({ queryKey: statusQuery.queryKey });
    },
  });

  const cancelRef = useRef(cancel);
  cancelRef.current = cancel;
  useEffect(() => {
    if (!pendingAuthUrl) {
      return;
    }
    const timer = setTimeout(() => {
      setPendingAuthUrl(null);
      cancelRef.current.mutate();
    }, SIGN_IN_POLL_TIMEOUT_MS);
    return () => clearTimeout(timer);
  }, [pendingAuthUrl]);

  const signOut = useMutation({
    ...hostTRPC.agent.piSubscriptionSignOut.mutationOptions(),
    onSuccess: () =>
      track(ANALYTICS_EVENTS.PI_SUBSCRIPTION_SIGNED_OUT, {
        provider: PI_SUBSCRIPTION_PROVIDER,
      }),
    onError: (error) =>
      toast.error("Couldn't sign out of ChatGPT", {
        description: error.message,
      }),
    onSettled: () =>
      void queryClient.invalidateQueries({ queryKey: statusQuery.queryKey }),
  });

  if (!flagEnabled) {
    return null;
  }

  if (statusLoading) {
    return (
      <SettingsCardRow
        label="ChatGPT account"
        description={CHATGPT_SUBSCRIPTION_SUMMARY}
      >
        <span className="text-(--gray-9) text-sm">Checking…</span>
      </SettingsCardRow>
    );
  }

  if (!loggedIn) {
    const pending = login.isPending || pendingAuthUrl !== null;
    return (
      <SettingsCardRow
        label="ChatGPT account"
        description={
          pendingAuthUrl
            ? "Finish signing in with your browser. This updates automatically"
            : CHATGPT_SUBSCRIPTION_SUMMARY
        }
      >
        <span className="flex items-center gap-2">
          {pendingAuthUrl && (
            <Button
              variant="link"
              size="sm"
              onClick={() => openExternalUrl(pendingAuthUrl)}
            >
              Reopen browser
            </Button>
          )}
          {pending ? (
            <Button
              variant="outline"
              size="sm"
              loading={cancel.isPending}
              disabled={cancel.isPending}
              onClick={() => cancel.mutate()}
            >
              Cancel
            </Button>
          ) : (
            <Button
              variant="outline"
              size="sm"
              loading={login.isPending}
              disabled={login.isPending}
              onClick={() => login.mutate()}
            >
              Connect ChatGPT account
            </Button>
          )}
        </span>
      </SettingsCardRow>
    );
  }

  return (
    <SettingsCardRow
      label="ChatGPT account"
      description={
        <span className="flex flex-col gap-1">
          <span>{CHATGPT_SUBSCRIPTION_SUMMARY}</span>
          <span className="flex items-center gap-1.5">
            <span
              className="inline-block h-1.5 w-1.5 rounded-full bg-(--green-9)"
              aria-hidden
            />
            Connected
          </span>
        </span>
      }
    >
      <Button
        variant="outline"
        size="sm"
        loading={signOut.isPending}
        disabled={signOut.isPending}
        onClick={() => signOut.mutate()}
      >
        Sign out
      </Button>
    </SettingsCardRow>
  );
}
