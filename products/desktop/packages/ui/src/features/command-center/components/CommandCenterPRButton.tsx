import { parseGitlabMergeRequestUrl } from "@posthog/core/git-interaction/prStatus";
import type { WorkspaceMode } from "@posthog/shared";
import { MergeRequestBadgeLink } from "../../git-interaction/components/MergeRequestBadgeLink";
import { PRBadgeLink } from "../../git-interaction/components/PRBadgeLink";
import { usePrDetails } from "../../git-interaction/usePrDetails";
import { useTaskPrUrls } from "../../git-interaction/useTaskPrUrl";

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
  const { primaryUrl: prUrl, otherUrls } = useTaskPrUrls(taskId, isCloud);
  const mergeRequest = isCloud ? parseGitlabMergeRequestUrl(prUrl) : null;

  const {
    meta: { state, merged, draft },
  } = usePrDetails(mergeRequest ? null : prUrl);

  if (prUrl && mergeRequest) {
    return (
      <MergeRequestBadgeLink url={prUrl} mergeRequest={mergeRequest} compact />
    );
  }

  if (!prUrl || state === null) return null;

  return (
    <PRBadgeLink
      prUrl={prUrl}
      prState={state}
      merged={merged}
      draft={draft}
      compact
      otherCount={otherUrls.length}
    />
  );
}
