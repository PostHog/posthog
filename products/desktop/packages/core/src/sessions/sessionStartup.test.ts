import { describe, expect, it } from "vitest";
import { readSessionStartupPhase } from "./sessionStartup";

describe("readSessionStartupPhase", () => {
  it.each(["_posthog/status", "__posthog/status"])(
    "reads startup progress from %s",
    (method) => {
      expect(
        readSessionStartupPhase({
          message: { method, params: { status: "setup_hooks" } },
        }),
      ).toBe("setup_hooks");
    },
  );

  it.each([
    null,
    {
      message: { method: "_posthog/status", params: { status: "compacting" } },
    },
    {
      message: { method: "session/update", params: { status: "setup_hooks" } },
    },
    { message: { method: "_posthog/status", params: null } },
  ])("ignores unrelated or malformed events", (event) => {
    expect(readSessionStartupPhase(event)).toBeUndefined();
  });
});
