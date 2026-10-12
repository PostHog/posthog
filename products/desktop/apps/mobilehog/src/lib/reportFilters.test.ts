import type { SignalReport } from "@posthog/shared/domain-types";
import { describe, expect, it } from "vitest";
import {
  hasOpenImplementationPr,
  openPullRequestUrl,
  reportFilterParams,
} from "./reportFilters";

const PR = "https://github.com/acme/app/pull/12";

function report(fields: Partial<SignalReport>): SignalReport {
  return { id: "r", ...fields } as SignalReport;
}

describe("reportFilters", () => {
  it.each([
    [
      "attention",
      {
        status: "ready,pending_input",
        actionability: "immediately_actionable,requires_human_input",
        ordering: "status,-priority,-created_at",
      },
    ],
    [
      "pull-requests",
      {
        status: "ready",
        has_implementation_pr: true,
        ordering: "status,-priority,-created_at",
      },
    ],
    ["dismissed", { status: "suppressed,resolved", ordering: "-updated_at" }],
  ] as const)("maps %s to its list params", (filter, params) => {
    expect(reportFilterParams(filter)).toEqual(params);
  });

  it.each([
    ["no PR", {}, false],
    [
      "an open PR",
      { implementation_pr_url: PR, implementation_pr_state: "open" },
      true,
    ],
    [
      "a draft PR",
      { implementation_pr_url: PR, implementation_pr_state: "draft" },
      true,
    ],
    ["a PR with no known state", { implementation_pr_url: PR }, true],
    [
      "a merged PR",
      { implementation_pr_url: PR, implementation_pr_state: "merged" },
      false,
    ],
    [
      "a closed PR",
      { implementation_pr_url: PR, implementation_pr_state: "closed" },
      false,
    ],
    [
      "a PR flagged merged",
      { implementation_pr_url: PR, implementation_pr_merged: true },
      false,
    ],
  ] as const)("treats a report with %s as open: %s", (_label, fields, open) => {
    expect(hasOpenImplementationPr(report(fields))).toBe(open);
  });

  it.each([
    [PR, PR],
    ["http://github.com/acme/app/pull/12", null],
    ["https://evil.example.com/acme/app/pull/12", null],
    ["mailto://github.com/acme/app/pull/1", null],
    ["javascript:alert(1)", null],
    ["myapp://github.com/acme/app/pull/1", null],
  ])("only opens %s as a GitHub PR link", (url, expected) => {
    expect(
      openPullRequestUrl(
        report({ implementation_pr_url: url, implementation_pr_state: "open" }),
      ),
    ).toBe(expected);
  });

  it("does not link a merged PR", () => {
    expect(
      openPullRequestUrl(
        report({
          implementation_pr_url: PR,
          implementation_pr_state: "merged",
        }),
      ),
    ).toBeNull();
  });
});
