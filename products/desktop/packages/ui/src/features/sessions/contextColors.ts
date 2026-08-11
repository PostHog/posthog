import type { ContextBreakdown } from "@posthog/ui/features/sessions/hooks/useContextUsage";

export interface CategoryStyle {
  key: keyof ContextBreakdown;
  label: string;
  color: string;
}

// Quill tokens, not Radix scale vars: the breakdown renders inside a quill
// popover portal, which sits outside the Radix Themes scope those vars are
// declared on and would draw the swatches as transparent.
export const CONTEXT_CATEGORIES: readonly CategoryStyle[] = [
  {
    key: "systemPrompt",
    label: "System prompt",
    color: "var(--muted-foreground)",
  },
  { key: "tools", label: "Tools", color: "var(--data-color-14)" },
  { key: "rules", label: "Rules", color: "var(--data-color-7)" },
  { key: "skills", label: "Skills", color: "var(--data-color-13)" },
  { key: "mcp", label: "MCP", color: "var(--data-color-9)" },
  { key: "subagents", label: "Subagents", color: "var(--data-color-8)" },
  { key: "conversation", label: "Conversation", color: "var(--primary)" },
] as const;

export function getOverallUsageColor(percentage: number): string {
  if (percentage >= 90) return "var(--destructive-foreground)";
  if (percentage >= 75) return "var(--data-color-12)";
  if (percentage >= 50) return "var(--warning-foreground)";
  return "var(--success-foreground)";
}

export function formatTokensCompact(tokens: number): string {
  if (tokens >= 1_000_000) return `${(tokens / 1_000_000).toFixed(1)}M`;
  if (tokens >= 1000) return `${Math.round(tokens / 1000)}K`;
  return tokens.toString();
}

/**
 * Formats a USD cost estimate for display. Sub-cent amounts collapse to
 * `<$0.01` so a non-zero spend never reads as free; everything else shows two
 * decimals ($0.42, $12.34).
 */
export function formatCostUsd(amount: number): string {
  if (amount <= 0) return "$0.00";
  if (amount < 0.01) return "<$0.01";
  return `$${amount.toFixed(2)}`;
}
