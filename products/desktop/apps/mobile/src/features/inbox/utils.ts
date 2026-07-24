import {
  EXTERNAL_INBOX_SOURCE_BY_PRODUCT,
  type SourceProduct,
} from "@posthog/shared";
import { differenceInHours, format, formatDistanceToNow } from "date-fns";
import type { InboxViewedProperties } from "@/lib/analytics";
import { DISMISSAL_REASON_OPTIONS } from "./constants";
import type {
  AvailableSuggestedReviewer,
  Signal,
  SignalReport,
  SignalReportOrderingField,
  SignalReportPriority,
  SignalReportStatus,
  SuggestedReviewer,
  SuggestedReviewerWriteEntry,
} from "./types";

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
  const type = source_type.replace(/_/g, " ");
  return `${product} · ${type}`;
}

const SIGNAL_SUMMARY_SECTION_HEADERS = [
  "What's happening",
  "Root cause",
  "How to resolve",
] as const;

/**
 * Inserts blank lines around signal report summary section headers so each
 * label and its body render on their own line (agent output often packs them
 * together, e.g. `**What's happening:** text **Root cause:** ...`).
 */
export function formatSignalReportSummaryMarkdown(content: string): string {
  let result = content;

  for (const header of SIGNAL_SUMMARY_SECTION_HEADERS) {
    const boldHeader = `\\*\\*${header}:\\*\\*`;
    result = result.replace(
      new RegExp(`([^\\n])\\s*(${boldHeader})`, "gi"),
      "$1\n\n$2",
    );
    result = result.replace(new RegExp(`(${boldHeader})\\s+`, "gi"), "$1\n\n");
  }

  return result;
}

/** Relative time for the last day, absolute "MMM d" beyond it. */
export function formatReportTimestamp(date: Date): string {
  return differenceInHours(new Date(), date) < 24
    ? formatDistanceToNow(date, { addSuffix: true })
    : format(date, "MMM d");
}

/**
 * Archive membership: `suppressed` (user-archived) and `resolved` (PR merged).
 * Only `suppressed` is restorable; `resolved` is terminal, shown for reference.
 */
export function isRestorableReport(
  report: Pick<SignalReport, "status">,
): boolean {
  return report.status === "suppressed";
}

/** Human label for a persisted dismissal reason, falling back to the raw code. */
export function dismissalReasonLabel(value: string): string {
  return (
    DISMISSAL_REASON_OPTIONS.find((o) => o.value === value)?.label ?? value
  );
}

export function inboxStatusLabel(status: SignalReportStatus): string {
  switch (status) {
    case "ready":
      return "Ready";
    case "resolved":
      return "Resolved";
    case "pending_input":
      return "Needs input";
    case "in_progress":
      return "Researching";
    case "candidate":
      return "Queued";
    case "potential":
      return "Gathering";
    case "failed":
      return "Failed";
    case "suppressed":
      return "Suppressed";
    case "deleted":
      return "Deleted";
    default:
      return status;
  }
}

/**
 * Build comma-separated `ordering` param for the API:
 * 1. Status rank (ready first)
 * 2. Suggested reviewer (current user first)
 * 3. User-selected field
 *
 * Priority is a coarse 5-bucket rank, so ties are broken by newest first.
 */
export function buildSignalReportListOrdering(
  field: SignalReportOrderingField,
  direction: "asc" | "desc",
): string {
  const fieldKey = direction === "desc" ? `-${field}` : field;
  const tiebreak = field === "priority" ? ",-created_at" : "";
  return `status,-is_suggested_reviewer,${fieldKey}${tiebreak}`;
}

/**
 * Ordering for the Archive view, which lists two terminal statuses
 * (`suppressed` + `resolved`). Unlike the pipeline ordering, it must not prefix
 * with `status`: that would group one terminal state ahead of the other before
 * the time sort, burying recent items behind older ones from the sibling status.
 */
export function buildArchiveListOrdering(
  field: SignalReportOrderingField,
  direction: "asc" | "desc",
): string {
  return direction === "desc" ? `-${field}` : field;
}

/**
 * Build a comma-separated status filter string for the API.
 */
export function buildStatusFilterParam(statuses: SignalReportStatus[]): string {
  return statuses.join(",");
}

/**
 * Build a comma-separated suggested reviewer filter for the API.
 */
export function buildSuggestedReviewerFilterParam(
  reviewerIds: string[],
): string | undefined {
  const normalized = reviewerIds.map((id) => id.trim()).filter(Boolean);
  if (normalized.length === 0) return undefined;
  return Array.from(new Set(normalized)).join(",");
}

export function buildPriorityFilterParam(
  priorities: SignalReportPriority[],
): string | undefined {
  if (priorities.length === 0) return undefined;
  return Array.from(new Set(priorities)).join(",");
}

export function filterReportsBySearch(
  reports: SignalReport[],
  query: string,
): SignalReport[] {
  const trimmed = query.trim();
  if (!trimmed) return reports;

  const lower = trimmed.toLowerCase();
  return reports.filter(
    (report) =>
      report.title?.toLowerCase().includes(lower) ||
      report.summary?.toLowerCase().includes(lower) ||
      report.id.toLowerCase().includes(lower),
  );
}

/**
 * Returns only reports that are actionable for the tinder-like card deck:
 * ready, immediately actionable, not already addressed.
 */
export function getActionableReports(reports: SignalReport[]): SignalReport[] {
  return reports.filter(
    (r) =>
      r.status === "ready" &&
      r.actionability === "immediately_actionable" &&
      !r.already_addressed,
  );
}

export function orderSuggestedReviewers(
  reviewers: SuggestedReviewer[],
  meUuid: string | null | undefined,
): SuggestedReviewer[] {
  if (!meUuid) return reviewers;
  const meIndex = reviewers.findIndex((r) => r.user?.uuid === meUuid);
  if (meIndex <= 0) return reviewers;
  return [reviewers[meIndex], ...reviewers.filter((_, i) => i !== meIndex)];
}

export interface ReviewerOption {
  uuid: string;
  name: string;
  email: string;
  github_login: string;
  isMe: boolean;
}

/** Deduplicate the available-reviewers list by uuid and sort "Me" first, then by name. */
export function buildReviewerOptions(
  reviewers: AvailableSuggestedReviewer[],
  currentUserUuid: string | undefined,
): ReviewerOption[] {
  const seen = new Set<string>();
  const options: ReviewerOption[] = [];

  for (const r of reviewers) {
    if (!r.uuid || seen.has(r.uuid)) continue;
    seen.add(r.uuid);
    options.push({
      uuid: r.uuid,
      name: r.name?.trim() || "",
      email: r.email?.trim() || "",
      github_login: r.github_login?.trim() || "",
      isMe: r.uuid === currentUserUuid,
    });
  }

  options.sort((a, b) => {
    if (a.isMe && !b.isMe) return -1;
    if (!a.isMe && b.isMe) return 1;
    return (a.name || a.email).localeCompare(b.name || b.email);
  });

  return options;
}

export function reviewerOptionLabel(r: ReviewerOption): string {
  const base = r.name || r.email || "Unknown user";
  return r.isMe ? `${base} (Me)` : base;
}

/** A reviewer in the artefact matches an org member by user uuid or (case-insensitive) login. */
export function reviewerMatchesAvailable(
  reviewer: SuggestedReviewer,
  available: AvailableSuggestedReviewer,
): boolean {
  if (reviewer.user?.uuid && reviewer.user.uuid === available.uuid) {
    return true;
  }
  return (
    !!reviewer.github_login &&
    !!available.github_login &&
    reviewer.github_login.toLowerCase() === available.github_login.toLowerCase()
  );
}

/**
 * Build the full-replacement write payload from a read-shape list. Kept reviewers
 * are sent by `github_login` so the server preserves their commits/name; an entry
 * with only a resolved user falls back to `user_uuid`. Entries with neither are
 * dropped.
 */
export function toSuggestedReviewerWriteContent(
  reviewers: SuggestedReviewer[],
): SuggestedReviewerWriteEntry[] {
  return reviewers
    .map((reviewer): SuggestedReviewerWriteEntry | null => {
      if (reviewer.github_login) return { github_login: reviewer.github_login };
      if (reviewer.user?.uuid) return { user_uuid: reviewer.user.uuid };
      return null;
    })
    .filter((entry): entry is SuggestedReviewerWriteEntry => entry !== null);
}

interface InboxViewedFilterState {
  sourceProductFilter: string[];
  statusFilter: SignalReportStatus[];
  suggestedReviewerFilter: string[];
  priorityFilter: SignalReportPriority[];
  /** Default status filter as defined in the filter store, used to detect whether the user has narrowed it. */
  defaultStatusFilter: SignalReportStatus[];
}

/**
 * Build the property payload for the `Inbox viewed` analytics event.
 *
 * Mirrors packages/ui/src/features/inbox/components/InboxSignalsTab.tsx so
 * desktop and mobile send the same shape into PostHog.
 */
export function buildInboxViewedProperties(
  reports: SignalReport[],
  totalCount: number,
  filters: InboxViewedFilterState,
): InboxViewedProperties {
  const priorityCounts = {
    P0: 0,
    P1: 0,
    P2: 0,
    P3: 0,
    P4: 0,
    unknown: 0,
  };
  const actionabilityCounts = {
    immediately_actionable: 0,
    requires_human_input: 0,
    not_actionable: 0,
    unknown: 0,
  };
  let readyCount = 0;
  for (const r of reports) {
    if (r.status === "ready") readyCount += 1;
    const p = r.priority;
    if (p === "P0" || p === "P1" || p === "P2" || p === "P3" || p === "P4") {
      priorityCounts[p] += 1;
    } else {
      priorityCounts.unknown += 1;
    }
    const a = r.actionability;
    if (
      a === "immediately_actionable" ||
      a === "requires_human_input" ||
      a === "not_actionable"
    ) {
      actionabilityCounts[a] += 1;
    } else {
      actionabilityCounts.unknown += 1;
    }
  }

  const statusFiltered =
    filters.statusFilter.length !== filters.defaultStatusFilter.length ||
    filters.statusFilter.some((s) => !filters.defaultStatusFilter.includes(s));
  const hasActiveFilters =
    statusFiltered ||
    filters.sourceProductFilter.length > 0 ||
    filters.suggestedReviewerFilter.length > 0 ||
    filters.priorityFilter.length > 0;

  return {
    report_count: reports.length,
    total_count: totalCount,
    ready_count: readyCount,
    has_active_filters: hasActiveFilters,
    source_product_filter: filters.sourceProductFilter,
    status_filter_count: filters.statusFilter.length,
    is_empty: totalCount === 0,
    priority_p0_count: priorityCounts.P0,
    priority_p1_count: priorityCounts.P1,
    priority_p2_count: priorityCounts.P2,
    priority_p3_count: priorityCounts.P3,
    priority_p4_count: priorityCounts.P4,
    priority_unknown_count: priorityCounts.unknown,
    actionability_immediately_actionable_count:
      actionabilityCounts.immediately_actionable,
    actionability_requires_human_input_count:
      actionabilityCounts.requires_human_input,
    actionability_not_actionable_count: actionabilityCounts.not_actionable,
    actionability_unknown_count: actionabilityCounts.unknown,
  };
}
