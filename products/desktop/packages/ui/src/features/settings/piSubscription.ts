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

// Reuses the same rollout flags as the Claude Code / Codex ACP adapters'
// own-subscription toggles, rather than a new Pi-specific flag: it's the
// same "let this cohort bring their own subscription" population, just
// applied to a second harness.
const FLAGS: Record<PiSubscriptionProvider, string> = {
  anthropic: CLAUDE_OWN_SUBSCRIPTION_FLAG,
  "openai-codex": CODEX_OWN_SUBSCRIPTION_FLAG,
};

/**
 * Thin read of pi-ai's own stored credential state (via `piSubscriptionStatus`,
 * which calls straight into pi's `ModelRuntime`). Whether a connected
 * provider is actually *used* is a separate, persisted choice — see
 * `piModelAccess` in the settings store and `effectivePiSubscriptionProvider`
 * below — exactly like Claude/Codex's own `claudeModelAccess`/
 * `codexModelAccess`: logging in does not by itself switch billing.
 */
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

/**
 * The provider a Pi session should actually use, folding in every gate at
 * once: the user's billing pick, that provider's rollout flag, whether it's
 * actually logged in, and cloud tasks always billing PostHog credits (same
 * rule as `effectiveModelAccess` for Claude/Codex). `undefined` means the
 * PostHog gateway.
 */
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
