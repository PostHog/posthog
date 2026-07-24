import type { WorkspaceMode } from "@posthog/shared";
import { PRBadgeLink } from "../../git-interaction/components/PRBadgeLink";
import { usePrDetails } from "../../git-interaction/usePrDetails";
import { useTaskPrUrl } from "../../git-interaction/useTaskPrUrl";

interface CommandCenterPRButtonProps {
  taskId: string;
  workspaceMode: WorkspaceMode | null;
}

/**
 * PR badge for a task cell in the command center. Same resolution rules as
 * `TaskActionsMenu` via `useTaskPrUrl`, gated by `usePrDetails` returning a
 * real PR state.
 */
export function CommandCenterPRButton({
  taskId,
  workspaceMode,
}: CommandCenterPRButtonProps) {
  const isCloud = workspaceMode === "cloud";
  const prUrl = useTaskPrUrl(taskId, isCloud);

  const {
    meta: { state, merged, draft },
  } = usePrDetails(prUrl);

  if (!prUrl || state === null) return null;

  return (
    <PRBadgeLink
      prUrl={prUrl}
      prState={state}
      merged={merged}
      draft={draft}
      compact
    />
  );
}
