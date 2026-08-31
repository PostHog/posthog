import type { ReportStatusFilter } from "@posthog/core/inbox/reportChannelScope";
import type { SignalReportPriority } from "@posthog/shared/types";

export interface ChannelReportsFilters {
  search: string;
  relevantToMeOnly: boolean;
  priorities: SignalReportPriority[];
  status: ReportStatusFilter;
}
