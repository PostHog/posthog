import { Badge, cn } from "@posthog/quill";
import type { ComponentProps } from "react";

const INBOX_BADGE_RADIUS_CLASS =
  "rounded-(--radius-1)! cursor-default select-none";

type InboxBadgeProps = ComponentProps<typeof Badge>;

export function InboxBadge({ className, ...props }: InboxBadgeProps) {
  return (
    <Badge className={cn(INBOX_BADGE_RADIUS_CLASS, className)} {...props} />
  );
}
