import { buildInboxViewedProperties } from "@posthog/core/inbox/engagement";
import {
  buildArchiveListOrdering,
  buildPriorityFilterParam,
  buildSignalReportListOrdering,
  INBOX_PIPELINE_STATUSES,
} from "@posthog/core/inbox/reportFiltering";
import { isRestorableReport } from "@posthog/core/inbox/reportMembership";
import { formatSignalReportSummaryMarkdown } from "@posthog/core/inbox/reportPresentation";
import { dismissalReasonLabel } from "@posthog/shared";
import type {
  Signal,
  SignalReport,
  SignalReportOrderingField,
  SignalReportStatus,
} from "@posthog/shared/domain-types";
import { describe, expect, it } from "vitest";
import { sourceLine } from "./utils";

function signal(source_product: string, source_type: string): Signal {
  return {
    signal_id: "s1",
    content: "",
    source_product,
    source_type,
    source_id: "id",
    weight: 1,
    timestamp: "",
    extra: {},
  };
}

function buildMobileInboxViewedProperties(
  reports: SignalReport[],
  totalCount: number,
  filters: {
    sourceProductFilter: string[];
    statusFilter: readonly SignalReportStatus[];
    suggestedReviewerFilter: string[];
    priorityFilter: string[];
    defaultStatusFilter: readonly SignalReportStatus[];
  },
) {
  return buildInboxViewedProperties({
    visibleReports: reports,
    totalCount,
    filters: { surface: "mobile", ...filters },
  });
}

function makeReport(
  partial: Partial<SignalReport> & Pick<SignalReport, "id">,
): SignalReport {
  return {
    title: null,
    summary: null,
    status: "ready",
    total_weight: 0,
    signal_count: 0,
    created_at: "2026-01-01T00:00:00Z",
    updated_at: "2026-01-01T00:00:00Z",
    artefact_count: 0,
    ...partial,
  };
}

describe("formatSignalReportSummaryMarkdown", () => {
  it.each([
    {
      name: "puts section body on a new line after the header",
      input:
        "**What's happening:** Error tracking issue keyed on `app:dashboard_query`.",
      expected:
        "**What's happening:**\n\nError tracking issue keyed on `app:dashboard_query`.",
    },
    {
      name: "splits consecutive headers packed on one line",
      input:
        "**What's happening:** Users hit rate limits. **Root cause:** Limiters are contended. **How to resolve:** Reduce blocking.",
      expected:
        "**What's happening:**\n\nUsers hit rate limits.\n\n**Root cause:**\n\nLimiters are contended.\n\n**How to resolve:**\n\nReduce blocking.",
    },
    {
      name: "leaves already-separated headers sane",
      input:
        "**What's happening:**\n\nUsers hit rate limits.\n\n**Root cause:**\n\nLimiters are contended.",
      expected:
        "**What's happening:**\n\nUsers hit rate limits.\n\n**Root cause:**\n\nLimiters are contended.",
    },
    {
      name: "leaves content without headers unchanged",
      input: "Plain summary with no structured sections.",
      expected: "Plain summary with no structured sections.",
    },
    {
      name: "matches headers case-insensitively",
      input: "**what's happening:** lowercase header body.",
      expected: "**what's happening:**\n\nlowercase header body.",
    },
  ])("$name", ({ input, expected }) => {
    expect(formatSignalReportSummaryMarkdown(input)).toBe(expected);
  });
});

describe("buildInboxViewedProperties", () => {
  it("emits zero counts for an empty list", () => {
    const props = buildMobileInboxViewedProperties([], 0, {
      sourceProductFilter: [],
      statusFilter: INBOX_PIPELINE_STATUSES,
      suggestedReviewerFilter: [],
      priorityFilter: [],
      defaultStatusFilter: INBOX_PIPELINE_STATUSES,
    });
    expect(props).toMatchObject({
      report_count: 0,
      total_count: 0,
      ready_count: 0,
      has_active_filters: false,
      is_empty: true,
      priority_p0_count: 0,
      priority_p1_count: 0,
      priority_p2_count: 0,
      priority_p3_count: 0,
      priority_p4_count: 0,
      priority_unknown_count: 0,
      actionability_immediately_actionable_count: 0,
      actionability_requires_human_input_count: 0,
      actionability_not_actionable_count: 0,
      actionability_unknown_count: 0,
    });
  });

  it("breaks visible reports down by priority and actionability", () => {
    const reports: SignalReport[] = [
      makeReport({
        id: "1",
        priority: "P0",
        actionability: "immediately_actionable",
        status: "ready",
      }),
      makeReport({
        id: "2",
        priority: "P2",
        actionability: "requires_human_input",
        status: "ready",
      }),
      makeReport({
        id: "3",
        priority: "P2",
        actionability: "not_actionable",
        status: "potential",
      }),
      makeReport({ id: "4", status: "failed" }),
    ];

    const props = buildMobileInboxViewedProperties(reports, 4, {
      sourceProductFilter: [],
      statusFilter: INBOX_PIPELINE_STATUSES,
      suggestedReviewerFilter: [],
      priorityFilter: [],
      defaultStatusFilter: INBOX_PIPELINE_STATUSES,
    });

    expect(props.report_count).toBe(4);
    expect(props.total_count).toBe(4);
    expect(props.ready_count).toBe(2);
    expect(props.priority_p0_count).toBe(1);
    expect(props.priority_p2_count).toBe(2);
    expect(props.priority_unknown_count).toBe(1);
    expect(props.actionability_immediately_actionable_count).toBe(1);
    expect(props.actionability_requires_human_input_count).toBe(1);
    expect(props.actionability_not_actionable_count).toBe(1);
    expect(props.actionability_unknown_count).toBe(1);
  });

  it("marks filters active when any of status/source/reviewer/priority differs from defaults", () => {
    const narrowed = buildMobileInboxViewedProperties([], 0, {
      sourceProductFilter: [],
      statusFilter: ["ready"],
      suggestedReviewerFilter: [],
      priorityFilter: [],
      defaultStatusFilter: INBOX_PIPELINE_STATUSES,
    });
    expect(narrowed.has_active_filters).toBe(true);
    expect(narrowed.status_filter_count).toBe(1);

    const sourced = buildMobileInboxViewedProperties([], 0, {
      sourceProductFilter: ["error_tracking"],
      statusFilter: INBOX_PIPELINE_STATUSES,
      suggestedReviewerFilter: [],
      priorityFilter: [],
      defaultStatusFilter: INBOX_PIPELINE_STATUSES,
    });
    expect(sourced.has_active_filters).toBe(true);
    expect(sourced.source_product_filter).toEqual(["error_tracking"]);

    const reviewer = buildMobileInboxViewedProperties([], 0, {
      sourceProductFilter: [],
      statusFilter: INBOX_PIPELINE_STATUSES,
      suggestedReviewerFilter: ["uuid-1"],
      priorityFilter: [],
      defaultStatusFilter: INBOX_PIPELINE_STATUSES,
    });
    expect(reviewer.has_active_filters).toBe(true);

    const prioritized = buildMobileInboxViewedProperties([], 0, {
      sourceProductFilter: [],
      statusFilter: INBOX_PIPELINE_STATUSES,
      suggestedReviewerFilter: [],
      priorityFilter: ["P0"],
      defaultStatusFilter: INBOX_PIPELINE_STATUSES,
    });
    expect(prioritized.has_active_filters).toBe(true);
  });

  it("treats a reordered default status set as not filtered", () => {
    const props = buildMobileInboxViewedProperties([], 0, {
      sourceProductFilter: [],
      statusFilter: [...INBOX_PIPELINE_STATUSES].reverse(),
      suggestedReviewerFilter: [],
      priorityFilter: [],
      defaultStatusFilter: INBOX_PIPELINE_STATUSES,
    });
    expect(props.has_active_filters).toBe(false);
  });
});

describe("buildSignalReportListOrdering", () => {
  it.each([
    {
      field: "priority" as SignalReportOrderingField,
      direction: "desc" as const,
      expected: "status,-priority,-created_at",
    },
    {
      field: "priority" as SignalReportOrderingField,
      direction: "asc" as const,
      expected: "status,priority,-created_at",
    },
    {
      field: "signal_count" as SignalReportOrderingField,
      direction: "desc" as const,
      expected: "status,-signal_count,priority",
    },
    {
      field: "total_weight" as SignalReportOrderingField,
      direction: "asc" as const,
      expected: "status,total_weight,priority",
    },
    {
      field: "created_at" as SignalReportOrderingField,
      direction: "desc" as const,
      expected: "status,-created_at,priority",
    },
    {
      field: "updated_at" as SignalReportOrderingField,
      direction: "asc" as const,
      expected: "status,updated_at,priority",
    },
  ])(
    "orders $field $direction as $expected",
    ({ field, direction, expected }) => {
      expect(buildSignalReportListOrdering(field, direction)).toBe(expected);
    },
  );
});

describe("buildPriorityFilterParam", () => {
  it.each([
    {
      name: "returns undefined for an empty selection",
      input: [],
      expected: undefined,
    },
    {
      name: "joins selected priorities with commas",
      input: ["P0", "P2"] as const,
      expected: "P0,P2",
    },
    {
      name: "dedupes repeated priorities",
      input: ["P1", "P1", "P3"] as const,
      expected: "P1,P3",
    },
  ])("$name", ({ input, expected }) => {
    expect(buildPriorityFilterParam([...input])).toBe(expected);
  });
});

describe("buildArchiveListOrdering", () => {
  it.each([
    { direction: "desc" as const, expected: "-updated_at" },
    { direction: "asc" as const, expected: "updated_at" },
  ])(
    "sorts by field without a status prefix ($direction)",
    ({ direction, expected }) => {
      expect(buildArchiveListOrdering("updated_at", direction)).toBe(expected);
    },
  );
});

describe("isRestorableReport", () => {
  it.each([
    { status: "suppressed" as SignalReportStatus, expected: true },
    { status: "resolved" as SignalReportStatus, expected: false },
    { status: "ready" as SignalReportStatus, expected: false },
    { status: "deleted" as SignalReportStatus, expected: false },
  ])("is $expected for $status", ({ status, expected }) => {
    expect(isRestorableReport({ status })).toBe(expected);
  });
});

describe("dismissalReasonLabel", () => {
  it.each([
    { value: "analysis_wrong", expected: "Agent's analysis is wrong" },
    { value: "other", expected: "Something else…" },
    { value: "totally_unknown_code", expected: "totally_unknown_code" },
  ])("maps $value", ({ value, expected }) => {
    expect(dismissalReasonLabel(value)).toBe(expected);
  });
});

describe("sourceLine", () => {
  it.each([
    {
      product: "error_tracking",
      type: "issue_created",
      expected: "Error tracking · New issue",
    },
    { product: "sentry", type: "issue", expected: "Sentry · issue" },
    {
      product: "mystery_source",
      type: "thing",
      expected: "mystery source · thing",
    },
  ])("labels $product", ({ product, type, expected }) => {
    expect(sourceLine(signal(product, type))).toBe(expected);
  });
});
