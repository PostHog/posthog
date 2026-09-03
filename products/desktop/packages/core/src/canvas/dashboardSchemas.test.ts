import { describe, expect, it } from "vitest";
import { canvasStateSetInput } from "./dashboardSchemas";

describe("canvasStateSetInput", () => {
  const base = { id: "canvas-1", scope: "user" as const, key: "k" };

  // A non-finite number serializes to JSON null, which the backend reads as a
  // delete. Rejecting it here is what stops a silent destructive write.
  it.each([
    ["NaN", Number.NaN],
    ["Infinity", Number.POSITIVE_INFINITY],
    ["-Infinity", Number.NEGATIVE_INFINITY],
    ["nested NaN", { avg: Number.NaN }],
    ["NaN in array", [1, Number.NaN]],
  ])("rejects a %s value", (_label, value) => {
    expect(canvasStateSetInput.safeParse({ ...base, value }).success).toBe(
      false,
    );
  });

  it.each([
    ["null (the delete sentinel)", null],
    ["a finite number", 0],
    ["a string", "hello"],
    ["a boolean", true],
    ["a plain object", { columns: 3, title: "board" }],
    ["an array", [1, 2, 3]],
  ])("accepts a %s value", (_label, value) => {
    expect(canvasStateSetInput.safeParse({ ...base, value }).success).toBe(
      true,
    );
  });
});
