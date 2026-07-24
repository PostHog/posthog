import type { DismissalReasonOptionValue } from "./constants";

export type SignalReportStatus =
  | "potential"
  | "candidate"
  | "in_progress"
  | "ready"
  | "failed"
  | "pending_input"
  | "resolved"
  | "suppressed"
  | "deleted";

export type SignalReportPriority = "P0" | "P1" | "P2" | "P3" | "P4";

export type SignalReportActionability =
  | "immediately_actionable"
  | "requires_human_input"
  | "not_actionable";

export interface SignalReport {
  id: string;
  title: string | null;
  summary: string | null;
  status: SignalReportStatus;
  total_weight: number;
  signal_count: number;
  signals_at_run?: number;
  created_at: string;
  updated_at: string;
  artefact_count: number;
  priority?: SignalReportPriority | null;
  actionability?: SignalReportActionability | null;
  already_addressed?: boolean | null;
  dismissal_reason?: DismissalReasonOptionValue | null;
  dismissal_note?: string | null;
  is_suggested_reviewer?: boolean;
  source_products?: string[];
  implementation_pr_url?: string | null;
}

export interface SignalReportsResponse {
  results: SignalReport[];
  count: number;
}

export type SignalReportOrderingField =
  | "priority"
  | "signal_count"
  | "total_weight"
  | "created_at"
  | "updated_at";

export interface SignalReportsQueryParams {
  limit?: number;
  offset?: number;
  status?: string;
  ordering?: string;
  source_product?: string;
  suggested_reviewers?: string;
  priority?: string;
}

export interface SignalProcessingStateResponse {
  paused_until: string | null;
}

export interface AvailableSuggestedReviewer {
  uuid: string;
  name: string;
  email: string;
  github_login: string;
}

export interface AvailableSuggestedReviewersResponse {
  results: AvailableSuggestedReviewer[];
  count: number;
}

export interface Signal {
  signal_id: string;
  content: string;
  source_product: string;
  source_type: string;
  source_id: string;
  weight: number;
  timestamp: string;
  extra: Record<string, unknown>;
}

export interface SignalFindingContent {
  signal_id: string;
  relevant_code_paths: string[];
  relevant_commit_hashes: Record<string, string>;
  data_queried: string;
  verified: boolean;
}

export interface PriorityJudgmentContent {
  explanation: string;
  priority: SignalReportPriority;
}

export interface ActionabilityJudgmentContent {
  explanation: string;
  actionability: SignalReportActionability;
  already_addressed: boolean;
}

export interface SuggestedReviewerCommit {
  sha: string;
  url: string;
  reason: string;
}

export interface SuggestedReviewerUser {
  id: number;
  uuid: string;
  email: string;
  first_name: string;
  last_name: string;
}

export interface SuggestedReviewer {
  github_login: string;
  github_name: string | null;
  relevant_commits: SuggestedReviewerCommit[];
  user: SuggestedReviewerUser | null;
}

export interface SuggestedReviewersArtefact {
  id: string;
  type: "suggested_reviewers";
  created_at: string;
  content: SuggestedReviewer[];
}

/**
 * Write shape for replacing the suggested_reviewers artefact. The server
 * canonicalizes to a lowercase `github_login`, with `user_uuid` winning when
 * both are supplied.
 */
export interface SuggestedReviewerWriteEntry {
  github_login?: string;
  user_uuid?: string;
  github_name?: string;
}

export interface ArtefactUser {
  uuid?: string;
  email: string;
  first_name?: string;
  last_name?: string;
}

export interface CommitContent {
  repository: string;
  branch: string;
  commit_sha: string;
  message: string;
  note?: string | null;
}

export interface TaskRunArtefactContent {
  task_id: string;
  product: string;
  type: string;
}

export interface CommitDiffResponse {
  diff: string;
  truncated: boolean;
}

/**
 * Fields shared by every artefact row. `created_by` / `task_id` carry
 * attribution: at most one is set — `created_by` for user writes, `task_id`
 * for agent writes, neither for system writes.
 */
interface BaseArtefact {
  id: string;
  created_at: string;
  created_by?: ArtefactUser | null;
  task_id?: string | null;
}

export type ReportArtefact =
  | (BaseArtefact & {
      type: "priority_judgment";
      content: PriorityJudgmentContent;
    })
  | (BaseArtefact & {
      type: "actionability_judgment";
      content: ActionabilityJudgmentContent;
    })
  | (BaseArtefact & { type: "signal_finding"; content: SignalFindingContent })
  | (BaseArtefact & { type: "commit"; content: CommitContent })
  | (BaseArtefact & { type: "task_run"; content: TaskRunArtefactContent })
  | (BaseArtefact & SuggestedReviewersArtefact)
  | (BaseArtefact & { type: string; content: unknown });

export interface SignalReportArtefactsResponse {
  results: ReportArtefact[];
  count: number;
}

export interface SignalReportSignalsResponse {
  signals: Signal[];
}
