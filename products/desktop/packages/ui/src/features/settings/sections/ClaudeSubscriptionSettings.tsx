import { useHostTRPC } from "@posthog/host-router/react";
import { Button, Switch } from "@posthog/quill";
import { ANALYTICS_EVENTS } from "@posthog/shared";
import { SettingsCardRow } from "@posthog/ui/features/settings/components/SettingsCard";
import {
  applyClaudeModelAccess,
  shouldShowClaudeSubscriptionControls,
  useClaudeSubscription,
} from "@posthog/ui/features/settings/useClaudeSubscription";
import { track } from "@posthog/ui/shell/analytics";
import { registerClaudeSubscription } from "@posthog/ui/shell/posthogAnalyticsImpl";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import type { ReactElement } from "react";

export function ClaudeSubscriptionSettings(): ReactElement | null {
  const subscription = useClaudeSubscription();
  const hostTRPC = useHostTRPC();
  const queryClient = useQueryClient();

  const statusQuery = hostTRPC.agent.claudeSubscriptionStatus.queryOptions();
  const { data: status, isFetching } = useQuery({
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

  const description = loggedIn ? (
    <span className="flex flex-col gap-1">
      <span>
        Local and worktree Claude sessions run on your Claude plan instead of
        PostHog credits. Cloud tasks always use PostHog credits
      </span>
      <span className="flex items-center gap-1.5">
        <span
          className="inline-block h-1.5 w-1.5 rounded-full bg-(--green-9)"
          aria-hidden
        />
        Claude Code logged in
      </span>
    </span>
  ) : (
    <span className="flex flex-col gap-1">
      <span>
        Run local and worktree Claude sessions on your Claude plan instead of
        PostHog credits. Log in once with the Claude Code CLI, then re-check
      </span>
      <span className="flex items-center gap-1.5">
        <span
          className="inline-block h-1.5 w-1.5 rounded-full bg-(--red-9)"
          aria-hidden
        />
        Not logged in
      </span>
      <code className="text-[11px] text-muted-foreground">
        Run claude in a terminal and use /login
      </code>
    </span>
  );

  return (
    <SettingsCardRow
      label="Use your Claude subscription"
      description={description}
    >
      <span className="flex items-center gap-2">
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
    </SettingsCardRow>
  );
}
