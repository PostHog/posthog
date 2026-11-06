import { ChecksIcon, DotsThreeIcon } from "@phosphor-icons/react";
import {
  Button,
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@posthog/quill";
import { ActivityIncludeMenuSection } from "@posthog/ui/features/canvas/components/ActivityIncludeMenuSection";
import { markLoadedReadLabel } from "@posthog/ui/features/canvas/components/activityFeed";
import type { ReactElement } from "react";

interface ActivityActionsMenuProps {
  loadedUnreadCount: number;
  totalUnreadCount: number;
  isMarkingRead: boolean;
  onMarkAllRead: () => void;
}

export function ActivityActionsMenu({
  loadedUnreadCount,
  totalUnreadCount,
  isMarkingRead,
  onMarkAllRead,
}: ActivityActionsMenuProps): ReactElement {
  return (
    <DropdownMenu>
      <DropdownMenuTrigger
        render={
          <Button
            type="button"
            variant="default"
            size="icon-sm"
            aria-label="Activity actions"
            loading={isMarkingRead}
            disabled={isMarkingRead}
          >
            <DotsThreeIcon size={14} weight="bold" />
          </Button>
        }
      />
      <DropdownMenuContent
        align="end"
        side="bottom"
        sideOffset={4}
        className="min-w-64"
      >
        <DropdownMenuItem
          disabled={isMarkingRead || loadedUnreadCount === 0}
          onClick={onMarkAllRead}
        >
          <ChecksIcon size={14} />
          {markLoadedReadLabel(loadedUnreadCount, totalUnreadCount)}
        </DropdownMenuItem>

        <DropdownMenuSeparator />
        <ActivityIncludeMenuSection />
      </DropdownMenuContent>
    </DropdownMenu>
  );
}
