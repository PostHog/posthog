export type SignalReportStatus =
  | "potential"
  | "candidate"
  | "in_progress"
  | "ready"
  | "resolved"
  | "failed"
  | "pending_input"
  | "suppressed"
  | "deleted";

export type SignalReportOrderingField =
  | "priority"
  | "signal_count"
  | "total_weight"
  | "created_at"
  | "updated_at"
  | SignalReportRankingOrderingField;

/**
 * Orders by the served ranking model's probability for one outcome head.
 * Staff only: the API rejects these fields for other users.
 */
export type SignalReportRankingOrderingField =
  | "ranking_pr_merged"
  | "ranking_pr_created"
  | "ranking_action"
  | "ranking_open";
