import { signalsConfigKeys } from "@posthog/core/inbox/inboxQuery";
import type {
  SignalReportPriority,
  SignalUserAutonomyConfig,
} from "@posthog/shared/types";
import { useAuthenticatedClient } from "@posthog/ui/features/auth/authClient";
import { toast } from "@posthog/ui/primitives/toast";
import { useQueryClient } from "@tanstack/react-query";
import { useCallback } from "react";

const USER_AUTONOMY_QUERY_KEY = signalsConfigKeys.userAutonomyConfig;

export interface SlackNotificationUpdates {
  integrationId?: number | null;
  channel?: string | null;
  minPriority?: string | null;
}

/**
 * Mutations that write to the per-user Self-driving autonomy config:
 * Slack notification preferences. Reads come from `useSignalUserAutonomyConfig`.
 */
export function useSignalUserAutonomyMutations() {
  const client = useAuthenticatedClient();
  const queryClient = useQueryClient();

  const handleUpdateSlackNotifications = useCallback(
    async (updates: SlackNotificationUpdates) => {
      if (!client) return;
      // Translate frontend camelCase to the API's snake_case body. Only include
      // keys the caller passed in, so other settings (e.g. autostart_priority)
      // are not wiped.
      const body: Record<string, number | string | null> = {};
      if ("integrationId" in updates) {
        body.slack_notification_integration_id = updates.integrationId ?? null;
      }
      if ("channel" in updates) {
        body.slack_notification_channel = updates.channel ?? null;
      }
      if ("minPriority" in updates) {
        body.slack_notification_min_priority = updates.minPriority ?? null;
      }

      const previous =
        queryClient.getQueryData<SignalUserAutonomyConfig | null>(
          USER_AUTONOMY_QUERY_KEY,
        );

      // Optimistic update built from the previous snapshot so unrelated fields
      // (autostart_priority, etc.) are preserved.
      const optimisticNext: SignalUserAutonomyConfig = {
        ...(previous ??
          ({ autostart_priority: null } as SignalUserAutonomyConfig)),
        ...("integrationId" in updates
          ? { slack_notification_integration_id: updates.integrationId ?? null }
          : {}),
        ...("channel" in updates
          ? { slack_notification_channel: updates.channel ?? null }
          : {}),
        ...("minPriority" in updates
          ? {
              slack_notification_min_priority:
                (updates.minPriority as
                  | SignalReportPriority
                  | null
                  | undefined) ?? null,
            }
          : {}),
      };
      queryClient.setQueryData<SignalUserAutonomyConfig | null>(
        USER_AUTONOMY_QUERY_KEY,
        optimisticNext,
      );

      try {
        const fresh = await client.updateSignalUserAutonomyConfig(body);
        queryClient.setQueryData<SignalUserAutonomyConfig | null>(
          USER_AUTONOMY_QUERY_KEY,
          fresh,
        );
      } catch (error: unknown) {
        queryClient.setQueryData<SignalUserAutonomyConfig | null>(
          USER_AUTONOMY_QUERY_KEY,
          previous ?? null,
        );
        const message =
          error instanceof Error
            ? error.message
            : "Failed to update Slack notification setting";
        toast.error(message);
      }
    },
    [client, queryClient],
  );

  return {
    handleUpdateSlackNotifications,
  };
}
