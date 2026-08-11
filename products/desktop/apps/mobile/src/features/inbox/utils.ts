import {
  EXTERNAL_INBOX_SOURCE_BY_PRODUCT,
  type SourceProduct,
} from "@posthog/shared";
import type { Signal } from "@posthog/shared/domain-types";

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

/** Roughly four lines of prose at the card's font size. */
const MAX_SUMMARY_EXCERPT_LENGTH = 320;

/**
 * Flattens a report summary's Markdown into the few lines of prose a swipe
 * card can show.
 *
 * The card is a triage surface, not a reader — the full rendered summary is
 * one tap away in the expanded view — so block syntax that only means
 * something with real layout (headings, bullets, fences) is dropped rather
 * than rendered, and the result is capped so a long summary can't cost a
 * large text layout on every card in the stack. Underscores survive: they
 * show up in identifiers far more often than as emphasis.
 */
export function summaryExcerpt(summary: string | null | undefined): string {
  if (typeof summary !== "string") return "";
  const flattened = summary
    .replace(/```[\s\S]*?```/g, " ")
    .replace(/!?\[([^\]]*)\]\([^)]*\)/g, "$1")
    .replace(/^\s{0,3}#{1,6}\s+/gm, "")
    .replace(/^\s*[-*+]\s+/gm, "")
    .replace(/^\s*\d+\.\s+/gm, "")
    .replace(/^\s*>\s?/gm, "")
    .replace(/[*`]/g, "")
    .replace(/\s+/g, " ")
    .trim();
  return flattened.length > MAX_SUMMARY_EXCERPT_LENGTH
    ? `${flattened.slice(0, MAX_SUMMARY_EXCERPT_LENGTH).trimEnd()}…`
    : flattened;
}
