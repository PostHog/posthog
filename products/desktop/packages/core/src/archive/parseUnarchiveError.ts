const BRANCH_NOT_FOUND_PATTERN = /Branch '(.+)' does not exist/;

export type UnarchiveErrorResult =
  | { kind: "branch-not-found"; branchName: string }
  | { kind: "other"; message: string };

export function parseUnarchiveError(error: unknown): UnarchiveErrorResult {
  const message = error instanceof Error ? error.message : String(error);
  const match = message.match(BRANCH_NOT_FOUND_PATTERN);
  if (match) {
    return { kind: "branch-not-found", branchName: match[1] };
  }
  return { kind: "other", message };
}
