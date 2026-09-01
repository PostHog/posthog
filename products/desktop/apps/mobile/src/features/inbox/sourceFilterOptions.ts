import type { SignalSourceConfig } from "@posthog/api-client/posthog-client";
import {
  EXTERNAL_INBOX_SOURCES,
  filterInboxSourceOptions,
  type SourceProduct,
} from "@posthog/shared";

export const SOURCE_PRODUCT_OPTIONS: { value: SourceProduct; label: string }[] =
  [
    { value: "session_replay", label: "Session replay" },
    { value: "error_tracking", label: "Error tracking" },
    { value: "llm_analytics", label: "AI observability" },
    { value: "conversations", label: "Conversations" },
    { value: "signals_scout", label: "Scout" },
    ...EXTERNAL_INBOX_SOURCES.map((source) => ({
      value: source.product,
      label: source.label,
    })),
  ];

export function narrowSourceProductOptions(
  configs: SignalSourceConfig[] | undefined,
  selected: SourceProduct[],
): { value: SourceProduct; label: string }[] {
  const enabled = configs
    ? new Set(configs.filter((c) => c.enabled).map((c) => c.source_product))
    : undefined;
  return filterInboxSourceOptions(SOURCE_PRODUCT_OPTIONS, enabled, selected);
}
