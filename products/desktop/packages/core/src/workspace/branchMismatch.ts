export function isBranchMismatch(
  linkedBranch: string | null,
  currentBranch: string | null,
): boolean {
  return !!linkedBranch && !!currentBranch && linkedBranch !== currentBranch;
}

export function shouldWarnBranchMismatch(
  linkedBranch: string | null,
  currentBranch: string | null,
  dismissed: boolean,
): boolean {
  return isBranchMismatch(linkedBranch, currentBranch) && !dismissed;
}
