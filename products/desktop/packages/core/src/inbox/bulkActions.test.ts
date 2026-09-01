import { describe, expect, it } from "vitest";
import { buildResolveRequest } from "./bulkActions";

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
