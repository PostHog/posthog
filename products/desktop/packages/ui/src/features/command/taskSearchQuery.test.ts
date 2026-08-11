import { describe, expect, it } from "vitest";
import { taskSearchDelay } from "./taskSearchQuery";

describe("taskSearchDelay", () => {
  it.each(["https://github.com/posthog/posthog/pull/123"])(
    "searches structured query %s immediately",
    (query) => expect(taskSearchDelay(query)).toBe(0),
  );

  it.each(["7", "#123"])("debounces numeric query %s", (query) =>
    expect(taskSearchDelay(query)).toBe(120),
  );

  it("debounces names", () => {
    expect(taskSearchDelay("release report")).toBe(120);
  });

  it.each(["", " ", "a", "#"])("does not remotely search %j", (query) => {
    expect(taskSearchDelay(query)).toBeNull();
  });
});
