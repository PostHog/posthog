import type { IconProps } from "@phosphor-icons/react";
import { DetailSection } from "@posthog/ui/features/inbox/components/DetailSection";
import type { ComponentType, ReactNode } from "react";

interface RightColumnSectionProps {
  Icon: ComponentType<IconProps>;
  title: string;
  rightSlot?: ReactNode;
  children: ReactNode;
}

/**
 * Right-column sections share the main column's card chrome so the detail
 * view reads as one card system. Kept as its own export so the two columns
 * can diverge again without touching every consumer.
 */
export function RightColumnSection(props: RightColumnSectionProps) {
  return <DetailSection {...props} />;
}
