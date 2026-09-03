import { useHostTRPC } from "@posthog/host-router/react";
import { Button } from "@posthog/quill";
import { ANALYTICS_EVENTS, type PiSubscriptionProvider } from "@posthog/shared";
import { SettingsCardRow } from "@posthog/ui/features/settings/components/SettingsCard";
import { usePiSubscription } from "@posthog/ui/features/settings/piSubscription";
import { toast } from "@posthog/ui/primitives/toast";
import { track } from "@posthog/ui/shell/analytics";
import { openExternalUrl } from "@posthog/ui/shell/openExternal";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { type ReactElement, useEffect, useRef, useState } from "react";

const SIGN_IN_POLL_TIMEOUT_MS = 10 * 60_000 + 15_000;

interface PiSubscriptionSettingsProps {
  provider: PiSubscriptionProvider;
  accountLabel: string;
  connectLabel: string;
  summary: string;
}

/**
 * Connect/disconnect only — no separate "use it" toggle. Once connected, Pi
 * task creation prefers this provider automatically over PostHog credits
 * (see `useTaskCreation`); there's nothing else to keep in sync here.
 */
export function PiSubscriptionSettings({
  provider,
  accountLabel,
  connectLabel,
  summary,
}: PiSubscriptionSettingsProps): ReactElement | null {
  const { flagEnabled } = usePiSubscription(provider);
  const hostTRPC = useHostTRPC();
  const queryClient = useQueryClient();
  // Non-null while a login is in flight or waiting on the browser callback.
  // Reopening the browser from here never calls the backend again — it just
  // re-opens the URL we already have, so it can't collide with the pending
  // attempt the way starting a brand new login would.
  const [pendingAuthUrl, setPendingAuthUrl] = useState<string | null>(null);

  const statusQuery = hostTRPC.agent.piSubscriptionStatus.queryOptions({
    provider,
  });
  const { data: status, isLoading: statusLoading } = useQuery({
    ...statusQuery,
    refetchInterval: (query) =>
      pendingAuthUrl && query.state.data?.loginState !== "logged-in"
        ? 2000
        : false,
  });
  const loggedIn = status?.loginState === "logged-in";

  useEffect(() => {
    if (!pendingAuthUrl || !loggedIn) return;
    setPendingAuthUrl(null);
    track(ANALYTICS_EVENTS.PI_SUBSCRIPTION_CONNECTED, { provider });
  }, [pendingAuthUrl, loggedIn, provider]);

  const login = useMutation({
    ...hostTRPC.agent.piSubscriptionLoginStart.mutationOptions(),
    onSuccess: ({ authUrl }) => {
      setPendingAuthUrl(authUrl);
      openExternalUrl(authUrl);
    },
    onError: (error) =>
      toast.error(`Couldn't start ${accountLabel} sign-in`, {
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

  // The backend's own login flow gives up after the same 10 minutes; clear
  // the UI (and free the waiting subprocess early) rather than polling past
  // it. A ref avoids re-arming the timer on every `cancel` mutation render.
  const cancelRef = useRef(cancel);
  cancelRef.current = cancel;
  useEffect(() => {
    if (!pendingAuthUrl) return;
    const timer = setTimeout(() => {
      setPendingAuthUrl(null);
      cancelRef.current.mutate({ provider });
    }, SIGN_IN_POLL_TIMEOUT_MS);
    return () => clearTimeout(timer);
  }, [pendingAuthUrl, provider]);

  const signOut = useMutation({
    ...hostTRPC.agent.piSubscriptionSignOut.mutationOptions(),
    onSuccess: () =>
      track(ANALYTICS_EVENTS.PI_SUBSCRIPTION_SIGNED_OUT, { provider }),
    onError: (error) =>
      toast.error(`Couldn't sign out of ${accountLabel}`, {
        description: error.message,
      }),
    onSettled: () =>
      void queryClient.invalidateQueries({ queryKey: statusQuery.queryKey }),
  });

  if (!flagEnabled) {
    return null;
  }

  // Avoids a flash of "Connect" for an already-connected account while the
  // first, local status check is still in flight.
  if (statusLoading) {
    return (
      <SettingsCardRow label={`${accountLabel} account`} description={summary}>
        <span className="text-(--gray-9) text-sm">Checking…</span>
      </SettingsCardRow>
    );
  }

  if (!loggedIn) {
    const pending = login.isPending || pendingAuthUrl !== null;
    return (
      <SettingsCardRow
        label={`${accountLabel} account`}
        description={
          pendingAuthUrl
            ? "Finish signing in with your browser. This updates automatically"
            : summary
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
              onClick={() => cancel.mutate({ provider })}
            >
              Cancel
            </Button>
          ) : (
            <Button
              variant="outline"
              size="sm"
              onClick={() => login.mutate({ provider })}
            >
              {connectLabel}
            </Button>
          )}
        </span>
      </SettingsCardRow>
    );
  }

  return (
    <SettingsCardRow
      label={`${accountLabel} account`}
      description={
        <span className="flex flex-col gap-1">
          <span>{summary}</span>
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
        onClick={() => signOut.mutate({ provider })}
      >
        Sign out
      </Button>
    </SettingsCardRow>
  );
}
