import {
  EXTERNAL_INBOX_SOURCE_BY_PRODUCT,
  type SourceProduct,
} from "@posthog/shared";
import type { Signal } from "@posthog/shared/domain-types";
import { differenceInHours, format, formatDistanceToNow } from "date-fns";

const ERROR_TRACKING_TYPE_LABELS: Record<string, string> = {
  issue_created: "New issue",
  issue_reopened: "Issue reopened",
  issue_spiking: "Volume spike",
};

export function sourceLine(signal: Signal): string {
  const { source_product, source_type } = signal;
  if (source_product === "error_tracking") {
    const label =
      ERROR_TRACKING_TYPE_LABELS[source_type] ?? source_type.replace(/_/g, " ");
    return `Error tracking · ${label}`;
  }
  if (source_product === "session_replay" && source_type === "session_problem")
    return "Session replay · Session problem";
  if (source_product === "llm_analytics" && source_type === "evaluation")
    return "AI observability · Evaluation";
  if (source_product === "zendesk" && source_type === "ticket")
    return "Zendesk · Ticket";
  if (source_product === "github" && source_type === "issue")
    return "GitHub · Issue";
  if (source_product === "linear" && source_type === "issue")
    return "Linear · Issue";
  if (
    source_product === "signals_scout" &&
    source_type === "cross_source_issue"
  )
    return "Scout · Cross-source issue";
  if (source_product === "signals_scout") return "Scout";
  if (source_product === "health_checks" && source_type === "health_issue")
    return "Health checks · Issue";
  const warehouseSource =
    EXTERNAL_INBOX_SOURCE_BY_PRODUCT[source_product as SourceProduct];
  const product = warehouseSource?.label ?? source_product.replace(/_/g, " ");
  return `${product} · ${source_type.replace(/_/g, " ")}`;
}
/** Relative time for the last day, absolute "MMM d" beyond it. */
export function formatReportTimestamp(date: Date): string {
  return differenceInHours(new Date(), date) < 24
    ? formatDistanceToNow(date, { addSuffix: true })
    : format(date, "MMM d");
}
