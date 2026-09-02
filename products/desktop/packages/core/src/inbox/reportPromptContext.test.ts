import type { Signal, SignalReport } from "@posthog/shared/types";
import { describe, expect, it } from "vitest";

import { buildReportPromptContext } from "./reportPromptContext";

function report(overrides: Partial<SignalReport> = {}): SignalReport {
  return {
    id: "report-1",
    title: "Return 400 instead of 500",
    summary: "A malformed PUT raises a bare KeyError.",
    status: "ready",
    priority: "P2",
    total_weight: 1,
    signal_count: 1,
    created_at: "2026-08-20T12:00:00Z",
    updated_at: "2026-08-20T12:00:00Z",
    artefact_count: 0,
    ...overrides,
  } as SignalReport;
}

function signal(overrides: Partial<Signal> = {}): Signal {
  return {
    signal_id: "sig-1",
    content: "New error tracking issue created: KeyError 'resource'",
    source_product: "error_tracking",
    source_type: "issue",
    source_id: "issue-1",
    weight: 1,
    timestamp: "2026-08-20T11:00:00Z",
    extra: {},
    ...overrides,
  };
}

describe("buildReportPromptContext", () => {
  it("carries the report body and evidence the agent needs", () => {
    const context = buildReportPromptContext(report(), [signal()]);
    expect(context).toContain("# Report: Return 400 instead of 500");
    expect(context).toContain("A malformed PUT raises a bare KeyError.");
    expect(context).toContain("Priority: P2");
    expect(context).toContain("## Evidence (1 signal)");
    expect(context).toContain("KeyError 'resource'");
  });

  it("caps oversized evidence and says what was omitted", () => {
    const signals = Array.from({ length: 25 }, (_, i) =>
      signal({ signal_id: `sig-${i}`, content: "x".repeat(5_000) }),
    );
    const context = buildReportPromptContext(report(), signals);
    expect(context).toContain("## Evidence (25 signals)");
    expect(context).toContain("### Signal 20");
    expect(context).not.toContain("### Signal 21");
    expect(context).toContain("5 more signals omitted");
    expect(context).toContain("… [truncated]");
  });

  it("degrades to placeholders when summary and evidence are missing", () => {
    const context = buildReportPromptContext(
      report({ title: null, summary: null, priority: null }),
      [],
    );
    expect(context).toContain("# Report: Untitled report");
    expect(context).toContain("(no summary)");
    expect(context).not.toContain("## Evidence");
    expect(context).not.toContain("Priority:");
  });
});
