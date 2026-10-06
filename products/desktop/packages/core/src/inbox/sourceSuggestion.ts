import type { SuggestedSourceProduct } from "@posthog/shared/types";

const SOURCE_SUGGESTION_PRODUCTS: Record<
  SuggestedSourceProduct,
  { path: string; actionLabel: string }
> = {
  logs: { path: "logs", actionLabel: "Set up logs" },
  session_replay: { path: "replay/home", actionLabel: "Set up session replay" },
  error_tracking: {
    path: "error_tracking",
    actionLabel: "Set up error tracking",
  },
  llm_analytics: {
    path: "ai-observability/dashboard",
    actionLabel: "Set up AI observability",
  },
};

/**
 * The project path of the landing page a report's product suggestion links to,
 * and its button label. Null for a product this client doesn't know yet, so a
 * backend that adds one ships before the desktop app learns about it.
 */
export function sourceSuggestionTarget(
  product: string,
): { path: string; actionLabel: string } | null {
  return SOURCE_SUGGESTION_PRODUCTS[product as SuggestedSourceProduct] ?? null;
}
