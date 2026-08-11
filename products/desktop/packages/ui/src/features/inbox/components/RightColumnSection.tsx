import {
  DetailSection,
  type DetailSectionProps,
} from "@posthog/ui/features/inbox/components/DetailSection";

/**
 * Right-column sections share the main column's card chrome so the detail
 * view reads as one card system. Kept as its own export so the two columns
 * can diverge again without touching every consumer.
 */
export function RightColumnSection(props: DetailSectionProps) {
  return <DetailSection {...props} />;
}
