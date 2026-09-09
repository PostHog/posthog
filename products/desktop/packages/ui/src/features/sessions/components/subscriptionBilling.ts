import type { Adapter } from "@posthog/shared";
import type {
  AdapterSubscription,
  WorkspaceModeForAccess,
} from "@posthog/ui/features/settings/adapterSubscription";
import { subscriptionModelAccess } from "@posthog/ui/features/settings/adapterSubscription";

export const PROVIDER_LABEL: Record<Adapter, string> = {
  claude: "Anthropic",
  codex: "OpenAI",
};

export const LOGIN_NOTE: Record<Adapter, { link: string; rest: string }> = {
  claude: {
    link: "Log in to Claude Code",
    rest: " to use Anthropic billing.",
  },
  codex: {
    link: "Connect ChatGPT",
    rest: " to use OpenAI billing.",
  },
};

export const SUBSCRIPTION_LOGIN_ACTION: Record<Adapter, string> = {
  claude: "claude-login",
  codex: "codex-login",
};

export const CLOUD_ONLY_REASON: Record<Adapter, string> = {
  claude:
    "Claude plan billing is unavailable for cloud tasks. Try again later.",
  codex:
    "OpenAI billing only works for local and worktree tasks. Cloud tasks always use PostHog.",
};

const CLOUD_TOKEN_MISSING_REASON =
  "Cloud tasks on your Anthropic plan need a saved Claude token. Add one in Settings, or select PostHog.";

export function cloudBillingAvailable(
  adapter: Adapter,
  subscription: AdapterSubscription,
): boolean {
  return adapter === "claude" && !!subscription.cloudFlagEnabled;
}

/** Whether the billing pick is offered at all: both surfaces hide together. */
export function subscriptionBillingVisible(
  adapter: Adapter,
  subscription: AdapterSubscription,
  workspaceMode: WorkspaceModeForAccess | undefined,
): boolean {
  if (workspaceMode !== "cloud") return subscription.flagEnabled;
  return (
    subscription.flagEnabled ||
    cloudBillingAvailable(adapter, subscription) ||
    !!subscription.cloudSubscriptionOn
  );
}

/**
 * Why the stored cloud pick cannot run, or null when it can. Starting a cloud
 * run on the provider plan needs the cloud flag and a saved token, neither of
 * which the access resolver reads, so the chip would otherwise name a plan the
 * run refuses to use. `cloudTokenSaved` is undefined while the check is still
 * pending.
 */
export function cloudBillingBlockReason(
  adapter: Adapter,
  subscription: AdapterSubscription,
  workspaceMode: WorkspaceModeForAccess | undefined,
  cloudTokenSaved: boolean | undefined,
): string | null {
  if (
    adapter !== "claude" ||
    workspaceMode !== "cloud" ||
    !subscription.cloudSubscriptionOn
  ) {
    return null;
  }
  if (!cloudBillingAvailable(adapter, subscription)) {
    return CLOUD_ONLY_REASON[adapter];
  }
  return cloudTokenSaved === false ? CLOUD_TOKEN_MISSING_REASON : null;
}

/**
 * Who pays for a run started now. Reads the resolved access rather than the
 * stored pick, because a missing provider login and a cloud task both send the
 * run to PostHog whatever the setting says.
 */
export function subscriptionBillingLabel(
  adapter: Adapter,
  subscription: AdapterSubscription,
  workspaceMode: WorkspaceModeForAccess | undefined,
  blockReason?: string | null,
): string {
  if (blockReason) return "Unavailable";
  return subscriptionModelAccess(subscription, workspaceMode ?? "local") ===
    "own-subscription"
    ? PROVIDER_LABEL[adapter]
    : "PostHog";
}

/** The label in a sentence, and why the pick did not apply where it did not. */
export function subscriptionBillingHint(
  adapter: Adapter,
  subscription: AdapterSubscription,
  workspaceMode: WorkspaceModeForAccess | undefined,
  blockReason?: string | null,
): string {
  if (blockReason) return blockReason;
  const mode = workspaceMode ?? "local";
  if (subscriptionModelAccess(subscription, mode) === "own-subscription") {
    return `This run bills to your ${PROVIDER_LABEL[adapter]} plan.`;
  }
  const onPostHog = "This run bills to PostHog.";
  if (mode === "cloud") {
    return subscription.subscriptionOn &&
      !cloudBillingAvailable(adapter, subscription)
      ? `${onPostHog} ${CLOUD_ONLY_REASON[adapter]}`
      : onPostHog;
  }
  return subscription.subscriptionOn && !subscription.loggedIn
    ? `${onPostHog} ${LOGIN_NOTE[adapter].link}${LOGIN_NOTE[adapter].rest}`
    : onPostHog;
}
