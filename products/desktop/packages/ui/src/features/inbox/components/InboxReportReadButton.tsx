import { Button, cn } from "@posthog/quill";
import { useInboxReportReadState } from "@posthog/ui/features/inbox/hooks/useInboxReportReadState";
import { RAIL_HOVER_ACTIONS_CLASS } from "@posthog/ui/features/sidebar/components/RailListItem";
import type { ReactElement } from "react";

export function InboxReportReadButton({
  reportId,
}: {
  reportId: string;
}): ReactElement | null {
  const { isUnread, enabled, setRead } = useInboxReportReadState(reportId);
  if (!enabled) return null;

  return (
    <Button
      variant="default"
      size="icon-sm"
      className={cn(!isUnread && RAIL_HOVER_ACTIONS_CLASS)}
      aria-label={isUnread ? "Mark report as read" : "Mark report as unread"}
      title={isUnread ? "Unread. Mark as read" : "Mark as unread"}
      onClick={() => setRead(isUnread)}
    >
      <span
        className={cn(
          "size-2 rounded-full",
          isUnread ? "bg-(--blue-9)" : "border border-(--gray-9)",
        )}
      />
    </Button>
  );
}
