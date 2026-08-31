import { describe, expect, it } from "vitest";
import { asInboxBackTarget } from "./useInboxBackTarget";

describe("asInboxBackTarget", () => {
  it.each([
    ["reports origin", { to: "/inbox/reports", label: "Back to reports" }],
    ["pulls origin", { to: "/inbox/pulls", label: "Back to pull requests" }],
    ["runs origin", { to: "/inbox/runs", label: "Back to runs" }],
    ["archive origin", { to: "/inbox/dismissed", label: "Back to archive" }],
  ])("accepts a valid %s", (_label, value) => {
    expect(asInboxBackTarget(value)).toEqual(value);
  });

  it.each([
    ["undefined (no history state)", undefined],
    ["null", null],
    ["a non-object", "reports"],
    ["a route outside the inbox", { to: "/tasks", label: "Back" }],
    ["a non-list inbox route", { to: "/inbox/reports/abc", label: "Back" }],
    ["a missing label", { to: "/inbox/reports" }],
    ["an empty label", { to: "/inbox/reports", label: "" }],
    ["a missing route", { label: "Back to reports" }],
    ["a non-string route", { to: 7, label: "Back" }],
  ])("rejects %s and falls back", (_label, value) => {
    expect(asInboxBackTarget(value)).toBeNull();
  });
});
