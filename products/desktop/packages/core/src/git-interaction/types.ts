export type GitMenuActionId =
  | "commit"
  | "push"
  | "sync"
  | "publish"
  | "create-pr"
  | "view-pr"
  | "branch-here";

export interface GitMenuAction {
  id: GitMenuActionId;
  label: string;
  enabled: boolean;
  disabledReason: string | null;
}

export type CreatePrStep =
  | "idle"
  | "creating-branch"
  | "committing"
  | "pushing"
  | "creating-pr"
  | "complete"
  | "error";
