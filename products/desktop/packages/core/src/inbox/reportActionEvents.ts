import type { InboxReportActionProperties } from "@posthog/shared/analytics-events";
import type { SignalReport } from "@posthog/shared/domain-types";
import { reportAgeHours } from "./engagement";

export interface ReportListSnapshotEntry {
  rank: number;
  title: string | null;
  createdAt: string | null;
  priority: string | null;
  actionability: string | null;
}

export interface ReportListSnapshot {
  byId: Map<string, ReportListSnapshotEntry>;
  listSize: number;
}

export function snapshotReportList(
  reports: SignalReport[],
): ReportListSnapshot {
  return {
    byId: new Map(
      reports.map(
        (report, index) =>
          [
            report.id,
            {
              rank: index,
              title: report.title,
              createdAt: report.created_at,
              priority: report.priority ?? null,
              actionability: report.actionability ?? null,
            } satisfies ReportListSnapshotEntry,
          ] as const,
      ),
    ),
    listSize: reports.length,
  };
}

export function buildBulkActionEvents(
  actionType: InboxReportActionProperties["action_type"],
  targetIds: string[],
  snapshot: ReportListSnapshot,
): InboxReportActionProperties[] {
  const isBulk = targetIds.length > 1;
  return targetIds.map((reportId) => {
    const entry = snapshot.byId.get(reportId);
    return {
      report_id: reportId,
      report_title: entry?.title ?? null,
      report_age_hours: reportAgeHours(entry?.createdAt),
      action_type: actionType,
      surface: "toolbar",
      is_bulk: isBulk,
      bulk_size: targetIds.length,
      rank: entry?.rank ?? -1,
      list_size: snapshot.listSize,
      priority: entry?.priority ?? null,
      actionability: entry?.actionability ?? null,
    };
  });
}

export type DetailActionExtra = Partial<
  Omit<
    InboxReportActionProperties,
    | "report_id"
    | "report_title"
    | "report_age_hours"
    | "action_type"
    | "surface"
    | "is_bulk"
    | "bulk_size"
    | "rank"
    | "list_size"
  >
>;

export type DetailActionEvent = Omit<
  InboxReportActionProperties,
  "rank" | "list_size" | "priority" | "actionability"
> & {
  priority?: string | null;
  actionability?: string | null;
};

export function buildDetailActionEvent(
  report: SignalReport,
  actionType: InboxReportActionProperties["action_type"],
  extra?: DetailActionExtra,
): DetailActionEvent {
  return {
    report_id: report.id,
    report_title: report.title,
    report_age_hours: reportAgeHours(report.created_at),
    action_type: actionType,
    surface: "detail_pane",
    is_bulk: false,
    bulk_size: 1,
    ...extra,
  };
}
