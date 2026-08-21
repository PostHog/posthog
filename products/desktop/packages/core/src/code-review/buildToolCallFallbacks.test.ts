import { describe, expect, it } from "vitest";
import { buildToolCallFallbacks } from "./buildToolCallFallbacks";

describe("buildToolCallFallbacks", () => {
  it("returns undefined when remote files exist", () => {
    expect(
      buildToolCallFallbacks(true, ["a"], () => undefined),
    ).toBeUndefined();
  });

  it("collects only paths that resolve a truthy diff", () => {
    const result = buildToolCallFallbacks(false, ["a", "b", "c"], (path) =>
      path === "b" ? undefined : { oldText: path, newText: `${path}!` },
    );
    expect(result?.size).toBe(2);
    expect(result?.get("a")).toEqual({ oldText: "a", newText: "a!" });
    expect(result?.has("b")).toBe(false);
    expect(result?.has("c")).toBe(true);
  });

  it("skips paths with no diff", () => {
    const result = buildToolCallFallbacks(false, ["a", "b"], (path) =>
      path === "a" ? { oldText: null, newText: "x" } : undefined,
    );
    expect(result?.size).toBe(1);
    expect(result?.has("a")).toBe(true);
    expect(result?.has("b")).toBe(false);
  });
});
