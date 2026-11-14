import { describe, expect, it } from "vitest";
import {
  canResolveReport,
  hasOpenImplementationPr,
  isTerminalReport,
  resolveReportRunVariant,
} from "./signal-report-state";

describe("report state", () => {
  it.each([
    ["potential", false, false, "queued"],
    ["candidate", false, false, "queued"],
    ["in_progress", false, false, "live"],
    ["pending_input", true, false, "live"],
    ["ready", true, false, "completed"],
    ["failed", true, false, "failed"],
    ["monitoring", true, true, "completed"],
    ["closed", true, true, "completed"],
    ["resolved", false, true, "completed"],
    ["suppressed", false, true, "completed"],
    ["deleted", false, true, "completed"],
  ] as const)(
    "handles %s reports",
    (status, canResolve, terminal, runVariant) => {
      expect(canResolveReport({ status })).toBe(canResolve);
      expect(isTerminalReport({ status })).toBe(terminal);
      expect(resolveReportRunVariant(status)).toBe(runVariant);
    },
  );

  it.each([
    [undefined, false, true],
    [null, false, true],
    ["unknown", false, true],
    ["draft", false, true],
    ["open", false, true],
    ["closed", false, false],
    ["merged", false, false],
    ["open", true, false],
  ] as const)(
    "checks PR state %s and merged flag %s",
    (state, merged, expected) => {
      expect(
        hasOpenImplementationPr({
          implementation_pr_url: "https://github.com/example/repo/pull/42",
          implementation_pr_state: state,
          implementation_pr_merged: merged,
        }),
      ).toBe(expected);
    },
  );

  it("requires a PR URL", () => {
    expect(hasOpenImplementationPr({ implementation_pr_state: "open" })).toBe(
      false,
    );
  });

  it.each([
    [[], false],
    [
      [
        {
          url: "https://github.com/example/repo/pull/42",
          state: "closed",
          merged: false,
        },
      ],
      false,
    ],
    [
      [
        {
          url: "https://github.com/example/repo/pull/42",
          state: "open",
          merged: false,
        },
      ],
      true,
    ],
    [
      [
        {
          url: "https://github.com/example/repo/pull/42",
          state: "merged",
          merged: true,
        },
        {
          url: "https://github.com/example/repo/pull/43",
          state: "draft",
          merged: false,
        },
      ],
      true,
    ],
  ] as const)(
    "prefers the PR list over legacy fields: %j",
    (pullRequests, expected) => {
      expect(
        hasOpenImplementationPr({
          implementation_pr_url: "https://github.com/example/repo/pull/1",
          implementation_pr_state: "open",
          pull_requests: pullRequests,
        }),
      ).toBe(expected);
    },
  );
});
