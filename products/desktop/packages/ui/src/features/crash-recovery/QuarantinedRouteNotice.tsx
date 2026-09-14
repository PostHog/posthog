import { useArchiveTask } from "@posthog/ui/features/archive/useArchiveTask";
import { router } from "@posthog/ui/router/router";
import { quarantinedTaskId } from "@posthog/ui/shell/quarantinedRoute";
import { type ReactElement, useState } from "react";
import { QuarantinedRouteDialog } from "./QuarantinedRouteDialog";

interface QuarantinedRouteNoticeProps {
  /** The route the host refused to load, in `router.history` form. */
  route: string;
}

/** Wires the quarantine dialog to the task it is about. */
export function QuarantinedRouteNotice({
  route,
}: QuarantinedRouteNoticeProps): ReactElement {
  const [open, setOpen] = useState(true);
  const [isArchiving, setIsArchiving] = useState(false);
  const { archiveTask } = useArchiveTask();
  const taskId = quarantinedTaskId(route);

  const handleArchive = async (): Promise<void> => {
    if (isArchiving || !taskId) return;
    setIsArchiving(true);
    try {
      await archiveTask({ taskId });
      setOpen(false);
    } finally {
      setIsArchiving(false);
    }
  };

  return (
    <QuarantinedRouteDialog
      open={open}
      canArchive={taskId !== null}
      isArchiving={isArchiving}
      onDismiss={() => setOpen(false)}
      onOpenAnyway={() => {
        setOpen(false);
        router.history.push(route);
      }}
      onArchive={() => void handleArchive()}
    />
  );
}
