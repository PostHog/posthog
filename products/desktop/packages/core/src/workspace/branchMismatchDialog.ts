import {
  ANALYTICS_EVENTS,
  type BranchMismatchActionProperties,
  type BranchMismatchWarningShownProperties,
} from "@posthog/shared";

export type BranchMismatchDialogAction =
  | "switch"
  | "continue"
  | "cancel"
  | "shown";

export interface BranchMismatchContext {
  taskId: string;
  linkedBranch: string | null;
  currentBranch: string | null;
  hasUncommittedChanges: boolean;
}

export interface CheckoutBranchRequest {
  directoryPath: string;
  branchName: string;
}

export type BranchMismatchAnalyticsEvent =
  | {
      event: typeof ANALYTICS_EVENTS.BRANCH_MISMATCH_WARNING_SHOWN;
      properties: BranchMismatchWarningShownProperties;
    }
  | {
      event: typeof ANALYTICS_EVENTS.BRANCH_MISMATCH_ACTION;
      properties: BranchMismatchActionProperties;
    };

export function decideBeforeSubmit(shouldWarn: boolean): boolean {
  return !shouldWarn;
}

export function buildBranchMismatchAnalyticsEvent(
  action: BranchMismatchDialogAction,
  context: BranchMismatchContext,
): BranchMismatchAnalyticsEvent | null {
  const { taskId, linkedBranch, currentBranch, hasUncommittedChanges } =
    context;
  if (!linkedBranch || !currentBranch) {
    return null;
  }

  if (action === "shown") {
    return {
      event: ANALYTICS_EVENTS.BRANCH_MISMATCH_WARNING_SHOWN,
      properties: {
        task_id: taskId,
        linked_branch: linkedBranch,
        current_branch: currentBranch,
        has_uncommitted_changes: hasUncommittedChanges,
      },
    };
  }

  return {
    event: ANALYTICS_EVENTS.BRANCH_MISMATCH_ACTION,
    properties: {
      task_id: taskId,
      action,
      linked_branch: linkedBranch,
      current_branch: currentBranch,
    },
  };
}

export function buildCheckoutBranchRequest(
  repoPath: string | null,
  linkedBranch: string | null,
): CheckoutBranchRequest | null {
  if (!repoPath || !linkedBranch) {
    return null;
  }
  return { directoryPath: repoPath, branchName: linkedBranch };
}

export function resolveSwitchErrorMessage(error: unknown): string {
  return error instanceof Error ? error.message : "Failed to switch branch";
}
