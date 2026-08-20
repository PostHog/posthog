import { filterInboxSourceOptions } from "@posthog/shared";
import type { SourceProduct } from "@posthog/shared/types";
import {
  INBOX_SOURCE_OPTIONS,
  type InboxSourceOption,
} from "@posthog/ui/features/inbox/filterOptions";
import { useSignalSourceConfigs } from "@posthog/ui/features/inbox/hooks/useSignalSourceConfigs";
import { useMemo } from "react";

/**
 * Source options worth offering in the inbox filter: the sources this project
 * has switched on, plus PostHog's own products. See `filterInboxSourceOptions`
 * for the rules.
 */
export function useInboxSourceFilterOptions(
  selected: SourceProduct[],
): InboxSourceOption[] {
  const { data: configs } = useSignalSourceConfigs();

  return useMemo(() => {
    if (!configs) {
      return filterInboxSourceOptions(
        INBOX_SOURCE_OPTIONS,
        undefined,
        selected,
      );
    }
    const enabled = new Set<string>();
    for (const config of configs) {
      if (config.enabled) enabled.add(config.source_product);
    }
    return filterInboxSourceOptions(INBOX_SOURCE_OPTIONS, enabled, selected);
  }, [configs, selected]);
}
