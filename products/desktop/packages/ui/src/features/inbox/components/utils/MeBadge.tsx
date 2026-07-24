import { EyeIcon } from "@phosphor-icons/react";
import { InboxBadge } from "@posthog/ui/features/inbox/components/utils/InboxBadge";
import { Tooltip } from "@radix-ui/themes";

/**
 * Mirror of `ForYouBadge` for use inline next to a reviewer entry that
 * resolves to the current user – same warning/eye treatment so the
 * reviewer row + the report-level "For you" badge feel like one system.
 */
export function MeBadge() {
  return (
    <Tooltip content="You are a suggested reviewer">
      <InboxBadge variant="warning" className="gap-1">
        <EyeIcon size={12} className="shrink-0" />
        You
      </InboxBadge>
    </Tooltip>
  );
}
