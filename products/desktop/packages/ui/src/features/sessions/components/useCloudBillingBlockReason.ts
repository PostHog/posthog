import { useServiceOptional } from "@posthog/di/react";
import type { Adapter } from "@posthog/shared";
import { cloudBillingBlockReason } from "@posthog/ui/features/sessions/components/subscriptionBilling";
import type {
  AdapterSubscription,
  WorkspaceModeForAccess,
} from "@posthog/ui/features/settings/adapterSubscription";
import {
  CLAUDE_SUBSCRIPTION_TOKEN_SETTINGS,
  type ClaudeSubscriptionTokenSettings,
  claudeSubscriptionTokenQueryKey,
} from "@posthog/ui/features/settings/claudeSubscriptionTokenSettings";
import { useQuery } from "@tanstack/react-query";

/**
 * Why the stored cloud pick cannot run, or null when it can. Reads the saved
 * token the same way task creation does, so the billing shown and the billing
 * a run gets cannot disagree.
 */
export function useCloudBillingBlockReason(
  adapter: Adapter,
  subscription: AdapterSubscription,
  workspaceMode: WorkspaceModeForAccess | undefined,
): string | null {
  const tokenStore = useServiceOptional<ClaudeSubscriptionTokenSettings>(
    CLAUDE_SUBSCRIPTION_TOKEN_SETTINGS,
  );
  const cloudPick =
    workspaceMode === "cloud" && !!subscription.cloudSubscriptionOn;
  const { data: tokenSaved } = useQuery({
    queryKey: claudeSubscriptionTokenQueryKey,
    queryFn: () => tokenStore?.has() ?? Promise.resolve(false),
    enabled: !!tokenStore && cloudPick,
    retry: false,
  });
  return cloudBillingBlockReason(
    adapter,
    subscription,
    workspaceMode,
    tokenStore ? tokenSaved : false,
  );
}
