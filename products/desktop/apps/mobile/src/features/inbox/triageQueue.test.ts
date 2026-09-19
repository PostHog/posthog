import type { ReportImplementationState } from "@posthog/core/inbox/reportImplementation";
import type { SignalReport } from "@posthog/shared/domain-types";
import { describe, expect, it } from "vitest";
import { filterReportsForTriage } from "./triageQueue";

function report(id: string): SignalReport {
  return { id } as SignalReport;
}

describe("filterReportsForTriage", () => {
  const reports = [report("a"), report("b"), report("c"), report("d")];

  it.each<{
    name: string;
    state: ReportImplementationState | null;
    keep: boolean;
  }>([
    { name: "no task attached", state: null, keep: true },
    { name: "task still working", state: "working", keep: false },
    { name: "task in PR review", state: "in_review", keep: false },
    { name: "task never checked yet", state: "checking", keep: false },
    { name: "task waiting on user", state: "needs_input", keep: true },
    { name: "task failed", state: "failed", keep: true },
    { name: "task cancelled", state: "cancelled", keep: true },
    { name: "task finished without a PR", state: "no_pr", keep: true },
    { name: "task lookup failed", state: "unknown", keep: true },
  ])("$name → keep=$keep", ({ state, keep }) => {
    const states = new Map([["a", state]]);
    const result = filterReportsForTriage([report("a")], [], states);
    expect(result.map((r) => r.id)).toEqual(keep ? ["a"] : []);
  });

  it("drops already-decided reports regardless of implementation state", () => {
    const states = new Map<string, ReportImplementationState | null>([
      ["a", "failed"],
      ["b", null],
    ]);
    const result = filterReportsForTriage(reports, ["a", "b"], states);
    expect(result.map((r) => r.id)).toEqual(["c", "d"]);
  });

  it("preserves ordering of reports the caller passed in", () => {
    const states = new Map<string, ReportImplementationState | null>([
      ["b", "working"],
    ]);
    const result = filterReportsForTriage(reports, [], states);
    expect(result.map((r) => r.id)).toEqual(["a", "c", "d"]);
  });
});
