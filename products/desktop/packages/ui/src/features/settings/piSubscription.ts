import { useHostTRPC } from "@posthog/host-router/react";
import {
  ANALYTICS_EVENTS,
  CLAUDE_OWN_SUBSCRIPTION_FLAG,
  CODEX_OWN_SUBSCRIPTION_FLAG,
  type PiModelAccess,
  type PiSubscriptionProvider,
} from "@posthog/shared";
import { useFeatureFlag } from "@posthog/ui/features/feature-flags/useFeatureFlag";
import type { WorkspaceModeForAccess } from "@posthog/ui/features/settings/adapterSubscription";
import { useSettingsStore } from "@posthog/ui/features/settings/settingsStore";
import { track } from "@posthog/ui/shell/analytics";
import { useHostCapabilities } from "@posthog/ui/shell/useHostCapabilities";
import { useQuery } from "@tanstack/react-query";

export type PiSubscriptionLoginState = "logged-in" | "logged-out" | "unknown";

export interface PiSubscription {
  flagEnabled: boolean;
  loggedIn: boolean;
  loginState: PiSubscriptionLoginState;
}

const FLAGS: Record<PiSubscriptionProvider, string> = {
  anthropic: CLAUDE_OWN_SUBSCRIPTION_FLAG,
  "openai-codex": CODEX_OWN_SUBSCRIPTION_FLAG,
};

export function usePiSubscription(
  provider: PiSubscriptionProvider,
): PiSubscription {
  const flagEnabled = useFeatureFlag(FLAGS[provider]) || import.meta.env.DEV;
  const { localWorkspaces } = useHostCapabilities();
  const hostTRPC = useHostTRPC();
  const { data: status } = useQuery({
    ...hostTRPC.agent.piSubscriptionStatus.queryOptions({ provider }),
    enabled: flagEnabled && localWorkspaces,
    staleTime: 30_000,
  });

  const loginState = status?.loginState ?? "unknown";
  return { flagEnabled, loggedIn: loginState === "logged-in", loginState };
}

export function effectivePiSubscriptionProvider(input: {
  modelAccess: PiModelAccess;
  anthropic: PiSubscription;
  codex: PiSubscription;
  workspaceMode: WorkspaceModeForAccess;
}): PiSubscriptionProvider | undefined {
  if (input.modelAccess === "posthog-gateway") return undefined;
  if (input.workspaceMode === "cloud") return undefined;
  const subscription =
    input.modelAccess === "anthropic" ? input.anthropic : input.codex;
  if (!subscription.flagEnabled || !subscription.loggedIn) return undefined;
  return input.modelAccess;
}

export function applyPiModelAccess(next: PiModelAccess): void {
  const state = useSettingsStore.getState();
  const prev = state.piModelAccess;
  if (prev === next) return;
  state.setPiModelAccess(next);
  track(ANALYTICS_EVENTS.SETTING_CHANGED, {
    setting_name: "pi_model_access",
    new_value: next,
    old_value: prev,
  });
}
