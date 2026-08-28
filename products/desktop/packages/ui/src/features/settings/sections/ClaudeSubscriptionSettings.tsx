import { useHostTRPC } from "@posthog/host-router/react";
import { Button, Switch } from "@posthog/quill";
import { ANALYTICS_EVENTS } from "@posthog/shared";
import { SettingsCardRow } from "@posthog/ui/features/settings/components/SettingsCard";
import {
  shouldShowClaudeSubscriptionControls,
  useClaudeSubscription,
} from "@posthog/ui/features/settings/useClaudeSubscription";
import { track } from "@posthog/ui/shell/analytics";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { type ReactElement, useState } from "react";
import {
  type ClaudeAuthAction,
  ClaudeAuthTerminalDialog,
} from "./ClaudeAuthTerminalDialog";

export function ClaudeSubscriptionSettings(): ReactElement | null {
  const subscription = useClaudeSubscription();
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
  const loggedIn = status?.loggedIn === true;

  const visible = shouldShowClaudeSubscriptionControls({
    flagEnabled: subscription.flagEnabled,
    adapter: "claude",
  });
  if (!visible) {
    return null;
  }

  const summary = loggedIn
    ? "Local and worktree Claude sessions run on your Claude plan instead of PostHog credits. Cloud tasks always use PostHog credits"
    : "Run local and worktree Claude sessions on your Claude plan instead of PostHog credits. Log in once with the Claude Code CLI, then re-check";

  const statusLine = ((): { color: string; label: string } => {
    if (isPending) {
      return { color: "bg-(--gray-9)", label: "Checking" };
    }
    if (isError) {
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
      {!loggedIn && !isPending && !isError ? (
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
          onClick={() => {
            void queryClient.invalidateQueries({
              queryKey: statusQuery.queryKey,
            });
            if (loggedIn) {
              track(ANALYTICS_EVENTS.CLAUDE_SUBSCRIPTION_CONNECTED);
            }
          }}
        >
          Re-check
        </Button>
        <Switch
          size="sm"
          checked={subscription.subscriptionOn}
          onCheckedChange={(checked) => {
            subscription.setSubscriptionOn(checked === true);
            void queryClient.invalidateQueries({
              queryKey: statusQuery.queryKey,
            });
          }}
        />
      </span>
      {authAction ? (
        <ClaudeAuthTerminalDialog
          action={authAction}
          onClose={() => setAuthAction(null)}
          onFinished={() => {
            void queryClient.invalidateQueries({
              queryKey: statusQuery.queryKey,
            });
          }}
        />
      ) : null}
    </SettingsCardRow>
  );
}
