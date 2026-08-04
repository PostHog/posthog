import { describe, expect, it } from "vitest";
import {
  type AutomationStatusPresentation,
  type AutomationTaskRunStatus,
  getAutomationStatusPresentation,
} from "./automationStatus";

describe("automationStatus", () => {
  it.each<{
    status: AutomationTaskRunStatus;
    expected: AutomationStatusPresentation | null;
  }>([
    {
      status: "not_started",
      expected: { label: "Queued", tone: "warning", iconKind: "queued" },
    },
    {
      status: "queued",
      expected: { label: "Queued", tone: "warning", iconKind: "queued" },
    },
    { status: "started", expected: null },
    { status: "in_progress", expected: null },
    {
      status: "completed",
      expected: { label: "Success", tone: "success", iconKind: "success" },
    },
    {
      status: "failed",
      expected: { label: "Failed", tone: "error", iconKind: "failed" },
    },
    {
      status: "cancelled",
      expected: { label: "Failed", tone: "error", iconKind: "failed" },
    },
  ])(
    "maps task-run status $status to renderer-neutral presentation data",
    ({ status, expected }) => {
      expect(
        getAutomationStatusPresentation({
          lastRunStatus: "success",
          lastTaskRunStatus: status,
        }),
      ).toEqual(expected);
    },
  );

  it.each([
    ["running", null],
    ["success", { label: "Success", tone: "success", iconKind: "success" }],
    ["failed", { label: "Failed", tone: "error", iconKind: "failed" }],
    [null, { label: "Never run", tone: "neutral", iconKind: "never-run" }],
    ["unknown", { label: "Never run", tone: "neutral", iconKind: "never-run" }],
  ] as const)(
    "falls back from automation status %j to semantic presentation data",
    (lastRunStatus, expected) => {
      expect(getAutomationStatusPresentation({ lastRunStatus })).toEqual(
        expected,
      );
    },
  );

  it("prioritizes linked task-run detail over the automation-level status", () => {
    expect(
      getAutomationStatusPresentation({
        lastRunStatus: "failed",
        lastTaskRunStatus: "completed",
      }),
    ).toEqual({
      label: "Success",
      tone: "success",
      iconKind: "success",
    });
  });

  it("does not expose renderer-specific class names", () => {
    expect(
      getAutomationStatusPresentation({ lastRunStatus: "success" }),
    ).not.toHaveProperty("className");
  });
});
