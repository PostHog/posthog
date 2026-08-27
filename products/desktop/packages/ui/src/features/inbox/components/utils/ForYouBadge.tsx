import { EyeIcon } from "@phosphor-icons/react";
import { InboxBadge } from "@posthog/ui/features/inbox/components/utils/InboxBadge";
import { Tooltip } from "@radix-ui/themes";

export function ForYouBadge() {
  return (
    <Tooltip content="You are a suggested reviewer">
      <InboxBadge variant="warning" className="gap-1">
        <EyeIcon size={12} className="shrink-0" />
        For you
      </InboxBadge>
    </Tooltip>
  );
}
