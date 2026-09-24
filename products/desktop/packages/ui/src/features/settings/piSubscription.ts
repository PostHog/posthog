import { useHostTRPC } from "@posthog/host-router/react";
import {
  ANALYTICS_EVENTS,
  CODEX_OWN_SUBSCRIPTION_FLAG,
  PI_SUBSCRIPTION_PROVIDER,
  type PiModelAccess,
  type PiSubscriptionProvider,
} from "@posthog/shared";
import { useFeatureFlag } from "@posthog/ui/features/feature-flags/useFeatureFlag";
import type { WorkspaceModeForAccess } from "@posthog/ui/features/settings/adapterSubscription";
import { useSettingsStore } from "@posthog/ui/features/settings/settingsStore";
import { track } from "@posthog/ui/shell/analytics";
import { useHostCapabilities } from "@posthog/ui/shell/useHostCapabilities";
import { useQuery } from "@tanstack/react-query";

export interface PiSubscription {
  flagEnabled: boolean;
  loggedIn: boolean;
}

export interface PiSubscriptionModel {
  id: string;
  name: string;
}

export function usePiSubscription(): PiSubscription {
  const flagEnabled =
    useFeatureFlag(CODEX_OWN_SUBSCRIPTION_FLAG) || import.meta.env.DEV;
  const { localWorkspaces } = useHostCapabilities();
  const hostTRPC = useHostTRPC();
  const { data: status } = useQuery({
    ...hostTRPC.agent.piSubscriptionStatus.queryOptions(),
    enabled: flagEnabled && localWorkspaces,
    staleTime: 30_000,
  });

  return { flagEnabled, loggedIn: status?.loginState === "logged-in" };
}

export function usePiSubscriptionModels(
  enabled: boolean,
): PiSubscriptionModel[] {
  const hostTRPC = useHostTRPC();
  const { data } = useQuery({
    ...hostTRPC.agent.piSubscriptionModels.queryOptions(),
    enabled,
    staleTime: 60_000,
  });
  return data?.models ?? [];
}

export function effectivePiSubscriptionProvider(input: {
  modelAccess: PiModelAccess;
  subscription: PiSubscription;
  workspaceMode: WorkspaceModeForAccess;
}): PiSubscriptionProvider | undefined {
  if (input.modelAccess === "posthog-gateway") {
    return undefined;
  }
  if (input.workspaceMode === "cloud") {
    return undefined;
  }
  if (!input.subscription.flagEnabled || !input.subscription.loggedIn) {
    return undefined;
  }
  return PI_SUBSCRIPTION_PROVIDER;
}

export function applyPiModelAccess(next: PiModelAccess): void {
  const state = useSettingsStore.getState();
  const prev = state.piModelAccess;
  if (prev === next) {
    return;
  }
  state.setPiModelAccess(next);
  track(ANALYTICS_EVENTS.SETTING_CHANGED, {
    setting_name: "pi_model_access",
    new_value: next,
    old_value: prev,
  });
}
