import { signalsConfigKeys } from "@posthog/core/inbox/inboxQuery";
import type { SignalTeamConfig } from "@posthog/shared/types";
import { useAuthenticatedClient } from "@posthog/ui/features/auth/authClient";
import { toast } from "@posthog/ui/primitives/toast";
import { useQueryClient } from "@tanstack/react-query";
import { useCallback } from "react";

const TEAM_CONFIG_QUERY_KEY = signalsConfigKeys.teamConfig;

/**
 * Mutations that write to the per-team Self-driving config:
 * default autostart priority, default Slack channel, and the per-repo
 * autostart base-branch map. Reads come from `useSignalTeamConfig`.
 */
export function useSignalTeamConfigMutations() {
  const client = useAuthenticatedClient();
  const queryClient = useQueryClient();

  const handleUpdateAutostartPriority = useCallback(
    async (priority: string) => {
      if (!client) return;
      try {
        await client.updateSignalTeamConfig({
          default_autostart_priority: priority,
        });
        await queryClient.invalidateQueries({
          queryKey: TEAM_CONFIG_QUERY_KEY,
        });
      } catch (error: unknown) {
        const message =
          error instanceof Error
            ? error.message
            : "Failed to update autostart priority";
        toast.error(message);
      }
    },
    [client, queryClient],
  );

  const handleUpdateTeamSlackChannel = useCallback(
    async (channel: string | null) => {
      if (!client) return;
      try {
        await client.updateSignalTeamConfig({
          default_slack_notification_channel: channel,
        });
        await queryClient.invalidateQueries({
          queryKey: TEAM_CONFIG_QUERY_KEY,
        });
      } catch (error: unknown) {
        const message =
          error instanceof Error
            ? error.message
            : "Failed to update default notification channel";
        toast.error(message);
      }
    },
    [client, queryClient],
  );

  const handleUpdateAutostartBaseBranches = useCallback(
    async (branches: Record<string, string>) => {
      if (!client) return;

      const previous = queryClient.getQueryData<SignalTeamConfig | null>(
        TEAM_CONFIG_QUERY_KEY,
      );

      if (previous) {
        const optimistic: SignalTeamConfig = {
          ...previous,
          autostart_base_branches: branches,
        };
        queryClient.setQueryData<SignalTeamConfig | null>(
          TEAM_CONFIG_QUERY_KEY,
          optimistic,
        );
      }

      try {
        const fresh = await client.updateSignalTeamConfig({
          autostart_base_branches: branches,
        });
        queryClient.setQueryData<SignalTeamConfig | null>(
          TEAM_CONFIG_QUERY_KEY,
          fresh,
        );
      } catch (error: unknown) {
        queryClient.setQueryData<SignalTeamConfig | null>(
          TEAM_CONFIG_QUERY_KEY,
          previous ?? null,
        );
        const message =
          error instanceof Error
            ? error.message
            : "Failed to update base branch setting";
        toast.error(message);
      }
    },
    [client, queryClient],
  );

  return {
    handleUpdateAutostartPriority,
    handleUpdateTeamSlackChannel,
    handleUpdateAutostartBaseBranches,
  };
}
