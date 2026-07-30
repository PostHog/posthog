import type { GitMenuAction, GitMenuActionId } from "./types";

interface GitState {
  repoPath?: string;
  isRepo: boolean;
  isRepoLoading: boolean;
  hasChanges: boolean;
  aheadOfRemote: number;
  behind: number;
  aheadOfDefault: number;
  hasRemote: boolean;
  isFeatureBranch: boolean;
  currentBranch: string | null;
  defaultBranch: string | null;
  ghStatus: { installed: boolean; authenticated: boolean } | null;
  repoInfo: unknown | null;
  prStatus: {
    prExists: boolean;
    baseBranch: string | null;
    headBranch: string | null;
    prUrl: string | null;
  } | null;
  isOnline: boolean;
}

const OFFLINE_REASON = "No internet connection";

interface GitComputed {
  actions: GitMenuAction[];
  primaryAction: GitMenuAction;
  pushDisabledReason: string | null;
  // Named like pushDisabledReason: a disabled create-pr is dropped from
  // `actions`, so its reason is only readable here.
  createPrDisabledReason: string | null;
  prBaseBranch: string | null;
  prHeadBranch: string | null;
  prUrl: string | null;
  baseReason: string | null;
  isDetachedHead: boolean;
}

type Check = [boolean, string];

function firstFailingCheck(checks: Check[]): string | null {
  for (const [condition, message] of checks) {
    if (condition) return message;
  }
  return null;
}

function makeAction(
  id: GitMenuActionId,
  label: string,
  disabledReason: string | null,
): GitMenuAction {
  return { id, label, enabled: !disabledReason, disabledReason };
}

function getRepoReason(s: GitState): string | null {
  return firstFailingCheck([
    [!s.repoPath, "Select a repository folder first."],
    [s.isRepoLoading, "Checking repository status..."],
    [!s.isRepo, "Not a git repository."],
  ]);
}

function isDetachedHead(s: GitState): boolean {
  return s.isRepo && !s.isRepoLoading && !s.currentBranch;
}

function isOnDefaultBranch(s: GitState): boolean {
  return (
    s.isRepo && !s.isRepoLoading && !!s.currentBranch && !s.isFeatureBranch
  );
}

function getPushDisabledReason(
  s: GitState,
  repoReason: string | null,
  opts?: { assumeWillHaveCommits?: boolean },
): string | null {
  if (repoReason) return repoReason;
  if (!s.isOnline) return OFFLINE_REASON;

  if (s.behind > 0) {
    return "Sync branch with remote first.";
  }

  if (!opts?.assumeWillHaveCommits) {
    if (s.hasRemote && s.aheadOfRemote === 0) {
      return "Branch is up to date.";
    }
    if (!s.hasRemote && s.aheadOfRemote === 0) {
      return "No commits to publish.";
    }
  }

  return null;
}

function getCreatePrDisabledReason(
  s: GitState,
  repoReason: string | null,
): string | null {
  if (repoReason) return repoReason;
  if (!s.isOnline) return OFFLINE_REASON;

  if (!s.ghStatus) return "Checking GitHub CLI status...";
  if (!s.ghStatus.installed) return "Install GitHub CLI: `brew install gh`";
  if (!s.ghStatus.authenticated)
    return "Authenticate GitHub CLI with `gh auth login`";
  if (!s.repoInfo) return "No GitHub remote detected.";

  if (s.prStatus?.prExists) return "PR already exists.";

  const hasShippableWork =
    s.hasChanges || s.aheadOfRemote > 0 || s.aheadOfDefault > 0 || !s.hasRemote;
  if (!hasShippableWork) return "No changes to ship.";

  return null;
}

function getCommitAction(
  s: GitState,
  repoReason: string | null,
): GitMenuAction {
  const reason = repoReason ?? (s.hasChanges ? null : "No changes to commit.");
  return makeAction("commit", "Commit", reason);
}

function getPushAction(
  s: GitState,
  pushDisabledReason: string | null,
): GitMenuAction {
  if (!s.hasRemote) {
    return makeAction("publish", "Publish Branch", pushDisabledReason);
  }
  if (s.behind > 0) {
    return makeAction("sync", "Sync", pushDisabledReason);
  }
  return makeAction("push", "Push", pushDisabledReason);
}

function getViewPrAction(s: GitState): GitMenuAction | null {
  if (s.prStatus?.prExists) return makeAction("view-pr", "View PR", null);
  return null;
}

function getCreatePrAction(
  createPrDisabledReason: string | null,
): GitMenuAction {
  return makeAction("create-pr", "Create PR", createPrDisabledReason);
}

function getPrimaryAction(
  createPrAction: GitMenuAction,
  commitAction: GitMenuAction,
  pushAction: GitMenuAction,
  viewPrAction: GitMenuAction | null,
): GitMenuAction {
  if (viewPrAction) {
    if (commitAction.enabled) return commitAction;
    if (pushAction.enabled) return pushAction;
    return viewPrAction;
  }

  if (createPrAction.enabled) return createPrAction;
  if (commitAction.enabled) return commitAction;
  if (pushAction.enabled) return pushAction;
  return commitAction;
}

export function computeGitInteractionState(input: GitState): GitComputed {
  const repoReason = getRepoReason(input);
  const detachedHead = isDetachedHead(input);

  if (detachedHead) {
    const branchAction = makeAction("branch-here", "New branch", repoReason);
    return {
      actions: [branchAction],
      primaryAction: branchAction,
      pushDisabledReason: "Create a branch first.",
      createPrDisabledReason: "Create a branch first.",
      prBaseBranch: input.defaultBranch,
      prHeadBranch: null,
      prUrl: null,
      baseReason: repoReason,
      isDetachedHead: true,
    };
  }

  const onDefaultBranch = isOnDefaultBranch(input);
  const createPrDisabledReason = getCreatePrDisabledReason(input, repoReason);
  const createPrAction = getCreatePrAction(createPrDisabledReason);

  if (onDefaultBranch) {
    const branchAction = makeAction("branch-here", "New branch", repoReason);
    const commitAction = getCommitAction(input, repoReason);

    const actions = input.hasChanges
      ? [createPrAction, branchAction, commitAction]
      : [branchAction];
    const primaryAction =
      input.hasChanges && createPrAction.enabled
        ? createPrAction
        : branchAction;

    return {
      actions,
      primaryAction,
      pushDisabledReason: "Create a feature branch first.",
      createPrDisabledReason,
      prBaseBranch: input.defaultBranch,
      prHeadBranch: input.currentBranch,
      prUrl: input.prStatus?.prUrl ?? null,
      baseReason: repoReason,
      isDetachedHead: false,
    };
  }

  const pushDisabledReason = getPushDisabledReason(input, repoReason);

  const commitAction = getCommitAction(input, repoReason);
  const pushAction = getPushAction(input, pushDisabledReason);
  const viewPrAction = getViewPrAction(input);
  const primaryAction = getPrimaryAction(
    createPrAction,
    commitAction,
    pushAction,
    viewPrAction,
  );

  const actions: GitMenuAction[] = [];
  if (createPrAction.enabled) actions.push(createPrAction);
  actions.push(commitAction, pushAction);
  if (viewPrAction) actions.push(viewPrAction);

  return {
    actions,
    primaryAction,
    pushDisabledReason: getPushDisabledReason(input, repoReason, {
      assumeWillHaveCommits: true,
    }),
    createPrDisabledReason,
    prBaseBranch: input.prStatus?.baseBranch ?? input.defaultBranch,
    prHeadBranch: input.prStatus?.headBranch ?? input.currentBranch,
    prUrl: input.prStatus?.prUrl ?? null,
    baseReason: repoReason,
    isDetachedHead: false,
  };
}
