import type { SourceProduct } from "@posthog/shared/types";
import {
  filterInboxSourceOptions,
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

  return useMemo(
    () =>
      filterInboxSourceOptions(
        configs &&
          new Set(
            configs.filter((c) => c.enabled).map((c) => c.source_product),
          ),
        selected,
      ),
    [configs, selected],
  );
}
