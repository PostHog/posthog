import type { ClaudeSubscriptionTokenStore } from "@posthog/core/cloud-task/identifiers";

export type ClaudeSubscriptionTokenSettings = Pick<
  ClaudeSubscriptionTokenStore,
  "has" | "save" | "clear"
>;

export const CLAUDE_SUBSCRIPTION_TOKEN_SETTINGS = Symbol.for(
  "posthog.ui.claudeSubscriptionTokenSettings",
);

export const claudeSubscriptionTokenQueryKey = [
  "claudeSubscriptionToken",
  "has",
] as const;

export function isValidClaudeSetupToken(value: string): boolean {
  const token = value.trim();
  return /^sk-ant-oat01-\S{29,}$/.test(token) && token.length <= 4096;
}
