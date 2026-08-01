import type { TaskRunStatus } from "@posthog/shared/domain-types";
import { describe, expect, it } from "vitest";
import {
  RUN_STATUS_FILTER_OPTIONS,
  RUN_STATUS_LABELS,
  runStatusLabel,
  runStatusVariant,
} from "./runStatus";

const ALL_STATUSES: TaskRunStatus[] = [
  "not_started",
  "queued",
  "in_progress",
  "completed",
  "failed",
  "cancelled",
];

describe("runStatusLabel", () => {
  it.each([
    ["completed", "Ready"],
    ["in_progress", "In progress"],
    ["not_started", "Not started"],
    ["queued", "Queued"],
    ["failed", "Failed"],
    ["cancelled", "Cancelled"],
  ] as const)("labels %s as %s", (status, expected) => {
    expect(runStatusLabel(status)).toBe(expected);
  });

  it.each([null, undefined])("returns null for %s", (status) => {
    expect(runStatusLabel(status)).toBeNull();
  });
});

describe("runStatusVariant", () => {
  it.each([
    ["completed", "success"],
    ["failed", "destructive"],
    ["in_progress", "info"],
    ["queued", "default"],
    ["not_started", "default"],
    ["cancelled", "default"],
  ] as const)("maps %s to %s", (status, expected) => {
    expect(runStatusVariant(status)).toBe(expected);
  });

  it("falls back to default when there is no run", () => {
    expect(runStatusVariant(null)).toBe("default");
  });
});

describe("RUN_STATUS_FILTER_OPTIONS", () => {
  it("leads with the any-status option", () => {
    expect(RUN_STATUS_FILTER_OPTIONS[0]).toEqual({
      value: null,
      label: "Any status",
    });
  });

  it("offers every run status, so none is silently unfilterable", () => {
    const offered = RUN_STATUS_FILTER_OPTIONS.map((o) => o.value).filter(
      (v) => v !== null,
    );
    expect(new Set(offered)).toEqual(new Set(ALL_STATUSES));
  });

  it("reuses the shared labels rather than restating them", () => {
    for (const option of RUN_STATUS_FILTER_OPTIONS) {
      if (option.value) {
        expect(option.label).toBe(RUN_STATUS_LABELS[option.value]);
      }
    }
  });
});
