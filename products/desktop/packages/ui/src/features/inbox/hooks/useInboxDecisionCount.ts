import { useInboxSectionCounts } from "@posthog/ui/features/inbox/hooks/useInboxSectionCounts";

/**
 * The number the inbox badges show: the server-side count of ready reports
 * under the current reviewer scope (and any persisted source/priority
 * filters). The same count the inbox page's "Needs a decision" header shows,
 * from the same queries — so the badge and the page cannot disagree, and
 * neither depends on how many pages a client happened to load.
 */
export function useInboxDecisionCount(): number {
  return useInboxSectionCounts().decision;
}
