import { isInboxRelevanceSortActive } from "@posthog/core/inbox/reportFiltering";
import { INBOX_SCOPE_FOR_YOU } from "@posthog/core/inbox/reportMembership";
import { usePersonalInboxEnabled } from "@posthog/ui/features/feature-flags/usePersonalInboxEnabled";
import { useInboxReviewerScopeStore } from "@posthog/ui/features/inbox/stores/inboxReviewerScopeStore";
import { useInboxSignalsFilterStore } from "@posthog/ui/features/inbox/stores/inboxSignalsFilterStore";

/**
 * Whether the sectioned inbox offers relevance order, and whether it is the
 * order in use. Sort controls and the list read this so they cannot disagree.
 */
export function useInboxRelevanceSort(): {
  available: boolean;
  active: boolean;
} {
  const personalInboxEnabled = usePersonalInboxEnabled();
  const scope = useInboxReviewerScopeStore((state) => state.scope);
  const sortChoice = useInboxSignalsFilterStore((state) => state.sortChoice);
  return {
    available: personalInboxEnabled && scope === INBOX_SCOPE_FOR_YOU,
    active: isInboxRelevanceSortActive({
      personalInboxEnabled,
      scope,
      sortChoice,
    }),
  };
}
