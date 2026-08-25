import { useInboxSectionCounts } from "@posthog/ui/features/inbox/hooks/useInboxSectionCounts";

/** The number of live reports shown in the top-level Self-driving badge. */
export function useInboxReportCount(): number {
  const { decision, monitoring } = useInboxSectionCounts();
  return decision + monitoring;
}
