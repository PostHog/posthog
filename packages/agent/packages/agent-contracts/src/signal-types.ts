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
  | "updated_at";
