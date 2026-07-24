import { describe, expect, it } from "vitest";
import { isContentlessTask } from "./domain-types";

describe("isContentlessTask", () => {
  it.each([
    { name: "empty strings", title: "", description: "" },
    { name: "whitespace only", title: "   ", description: "\n\t " },
    { name: "null fields", title: null, description: null },
    { name: "undefined fields", title: undefined, description: undefined },
  ])("returns true for a placeholder task ($name)", (task) => {
    expect(isContentlessTask(task)).toBe(true);
  });

  it.each([
    { name: "a description", title: "", description: "Fix the login bug" },
    { name: "a title", title: "Fix the login bug", description: "" },
    {
      name: "a title and description",
      title: "Fix the login bug",
      description: "Fix the login bug",
    },
    { name: "padded content", title: "  Hi  ", description: "" },
  ])("returns false when the task has content ($name)", (task) => {
    expect(isContentlessTask(task)).toBe(false);
  });
});
