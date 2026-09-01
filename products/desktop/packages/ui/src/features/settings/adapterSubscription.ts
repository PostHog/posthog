import { useHostTRPC } from "@posthog/host-router/react";
import {
  type Adapter,
  ANALYTICS_EVENTS,
  CLAUDE_OWN_SUBSCRIPTION_FLAG,
  CODEX_OWN_SUBSCRIPTION_FLAG,
  type ModelAccess,
} from "@posthog/shared";
import { useFeatureFlag } from "@posthog/ui/features/feature-flags/useFeatureFlag";
import {
  type SettingsStore,
  useSettingsStore,
} from "@posthog/ui/features/settings/settingsStore";
import { track } from "@posthog/ui/shell/analytics";
import { registerAdapterSubscription } from "@posthog/ui/shell/posthogAnalyticsImpl";
import { useHostCapabilities } from "@posthog/ui/shell/useHostCapabilities";
import { useQuery } from "@tanstack/react-query";

export interface SubscriptionStatus {
  loginState: "logged-in" | "logged-out" | "unknown";
}

export type WorkspaceModeForAccess = "local" | "worktree" | "cloud";

interface AdapterSubscriptionSpec {
  flag: string;
  settingName: string;
  statusProcedure: "claudeSubscriptionStatus" | "codexSubscriptionStatus";
  readAccess: (state: SettingsStore) => ModelAccess;
  writeAccess: (state: SettingsStore, next: ModelAccess) => void;
}

const SPECS: Record<Adapter, AdapterSubscriptionSpec> = {
  claude: {
    flag: CLAUDE_OWN_SUBSCRIPTION_FLAG,
    settingName: "claude_model_access",
    statusProcedure: "claudeSubscriptionStatus",
    readAccess: (state) => state.claudeModelAccess,
    writeAccess: (state, next) => state.setClaudeModelAccess(next),
  },
  codex: {
    flag: CODEX_OWN_SUBSCRIPTION_FLAG,
    settingName: "codex_model_access",
    statusProcedure: "codexSubscriptionStatus",
    readAccess: (state) => state.codexModelAccess,
    writeAccess: (state, next) => state.setCodexModelAccess(next),
  },
};

export function subscriptionNeedsConnection(input: {
  flagEnabled: boolean;
  subscriptionOn: boolean;
  status: SubscriptionStatus | undefined;
}): boolean {
  return (
    input.flagEnabled &&
    input.subscriptionOn &&
    input.status?.loginState === "logged-out"
  );
}

export function effectiveModelAccess(input: {
  flagEnabled: boolean;
  subscriptionOn: boolean;
  loginState: "logged-in" | "logged-out" | "unknown";
  workspaceMode: WorkspaceModeForAccess;
}): ModelAccess {
  const usesOwnSubscription =
    input.flagEnabled &&
    input.subscriptionOn &&
    input.loginState === "logged-in" &&
    input.workspaceMode !== "cloud";
  return usesOwnSubscription ? "own-subscription" : "posthog-gateway";
}

export function applyModelAccess(
  adapter: Adapter,
  next: ModelAccess,
  connected: boolean,
): void {
  const spec = SPECS[adapter];
  const state = useSettingsStore.getState();
  const prev = spec.readAccess(state);
  // Always sync the connected super property. Only the setting write and
  // the SETTING_CHANGED event are gated on an access change, because a
  // login/logout transition can flip `connected` while `ModelAccess` stays
  // the same.
  if (prev !== next) {
    spec.writeAccess(state, next);
    track(ANALYTICS_EVENTS.SETTING_CHANGED, {
      setting_name: spec.settingName,
      new_value: next,
      old_value: prev,
    });
  }
  registerAdapterSubscription(adapter, { access: next, connected });
}

export async function registerSubscriptionAtBoot(
  adapter: Adapter,
  fetchStatus: () => Promise<SubscriptionStatus>,
  flagEnabled: boolean,
): Promise<void> {
  await settingsHydrated();
  const access: ModelAccess = flagEnabled
    ? SPECS[adapter].readAccess(useSettingsStore.getState())
    : "posthog-gateway";
  registerAdapterSubscription(adapter, { access, connected: false });
  const status = await fetchStatus();
  // Re-read the setting after the probe. A user can change the toggle while
  // the status check is in flight; the earlier `access` value is stale.
  const freshAccess = flagEnabled
    ? SPECS[adapter].readAccess(useSettingsStore.getState())
    : "posthog-gateway";
  registerAdapterSubscription(adapter, {
    access: freshAccess,
    connected: status.loginState === "logged-in",
  });
}

function settingsHydrated(): Promise<void> {
  if (useSettingsStore.getState()._hasHydrated) return Promise.resolve();
  return new Promise((resolve) => {
    const unsubscribe = useSettingsStore.subscribe((state) => {
      if (state._hasHydrated) {
        unsubscribe();
        resolve();
      }
    });
  });
}

export interface AdapterSubscription {
  flagEnabled: boolean;
  subscriptionOn: boolean;
  status: SubscriptionStatus | undefined;
  loggedIn: boolean;
  loginState: "logged-in" | "logged-out" | "unknown";
  needsConnection: boolean;
  setSubscriptionOn: (on: boolean) => void;
}

export function useAdapterSubscription(adapter: Adapter): AdapterSubscription {
  const spec = SPECS[adapter];
  const flagEnabled = useFeatureFlag(spec.flag) || import.meta.env.DEV;
  const modelAccess = useSettingsStore(spec.readAccess);
  const { localWorkspaces } = useHostCapabilities();
  const hostTRPC = useHostTRPC();
  // Short stale time so a login or logout between actions does not stick. The
  // desktop client default is five minutes, which can route a task through the
  // wrong billing source after the user changes state.
  const { data: status } = useQuery({
    ...hostTRPC.agent[spec.statusProcedure].queryOptions(),
    enabled: flagEnabled && localWorkspaces,
    staleTime: 30_000,
  });

  const subscriptionOn = modelAccess === "own-subscription";
  const loggedIn = status?.loginState === "logged-in";
  const loginState = status?.loginState ?? "unknown";

  return {
    flagEnabled,
    subscriptionOn,
    status,
    loggedIn,
    loginState,
    needsConnection: subscriptionNeedsConnection({
      flagEnabled,
      subscriptionOn,
      status,
    }),
    setSubscriptionOn: (on) =>
      applyModelAccess(
        adapter,
        on ? "own-subscription" : "posthog-gateway",
        loggedIn,
      ),
  };
}
