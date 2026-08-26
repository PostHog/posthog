import { describe, expect, it } from "vitest";
import { rewriteSavedLocation } from "./route-migrations";

describe("rewriteSavedLocation", () => {
  it("normalizes root rewrites to one leading slash", () => {
    expect(rewriteSavedLocation("/website/home//tasks/123")).toBe("/tasks/123");
  });

  it("preserves query and hash suffixes on root rewrites", () => {
    expect(rewriteSavedLocation("/website/home?tab=recent")).toBe(
      "/?tab=recent",
    );
    expect(rewriteSavedLocation("/website/home#section")).toBe("/#section");
  });
});
