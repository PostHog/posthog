import { describe, expect, it } from "vitest";
import { buildResolveRequest, buildSnoozeRequest } from "./bulkActions";

describe("buildSnoozeRequest", () => {
  it("sends a plain snooze when no dismissal drove it", () => {
    expect(buildSnoozeRequest()).toEqual({ state: "potential", snooze_for: 1 });
  });

  it("carries the reason and clamped note when a dismissal drove the snooze", () => {
    expect(
      buildSnoozeRequest({ reason: "already_fixed", note: "Shipped in v2" }),
    ).toEqual({
      state: "potential",
      snooze_for: 1,
      dismissal_reason: "already_fixed",
      dismissal_note: "Shipped in v2",
    });
    expect(
      buildSnoozeRequest({ reason: "already_fixed", note: "x".repeat(5000) })
        .dismissal_note,
    ).toHaveLength(4000);
  });
});

describe("buildResolveRequest", () => {
  it("keeps the structured reason and trims the optional note", () => {
    expect(
      buildResolveRequest("fixed_outside_posthog", "  Fixed in v2  "),
    ).toEqual({
      state: "resolved",
      dismissal_reason: "fixed_outside_posthog",
      dismissal_note: "Fixed in v2",
    });
    expect(buildResolveRequest("pr_merged", "   ")).toEqual({
      state: "resolved",
      dismissal_reason: "pr_merged",
    });
  });
});
