import { ArrowRightIcon } from "@phosphor-icons/react";
import { Button } from "@posthog/quill";
import { useInboxSignalsFilterStore } from "@posthog/ui/features/inbox/stores/inboxSignalsFilterStore";
import { navigateToInbox } from "@posthog/ui/router/navigationBridge";
import type { ReactElement } from "react";

interface InboxActivityOverflowRowProps {
  count: number;
  onOpened?: () => void;
}

export function InboxActivityOverflowRow({
  count,
  onOpened,
}: InboxActivityOverflowRowProps): ReactElement {
  const setPriorityFilter = useInboxSignalsFilterStore(
    (state) => state.setPriorityFilter,
  );

  const viewMore = (): void => {
    setPriorityFilter(["P1"]);
    navigateToInbox();
    onOpened?.();
  };

  return (
    <Button
      type="button"
      left
      className="h-auto w-full py-1.5 text-left text-muted-foreground"
      onClick={viewMore}
    >
      <span className="w-4 shrink-0" />
      <span className="min-w-0 flex-1 truncate text-[13px]">
        View {count} more in Self-driving
      </span>
      <ArrowRightIcon size={13} className="shrink-0" />
    </Button>
  );
}
