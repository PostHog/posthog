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
 * Who pays for a run started now. Reads the resolved access rather than the
 * stored pick, because a missing provider login and a cloud task both send the
 * run to PostHog whatever the setting says.
 */
export function subscriptionBillingLabel(
  adapter: Adapter,
  subscription: AdapterSubscription,
  workspaceMode: WorkspaceModeForAccess | undefined,
): string {
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
): string {
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
