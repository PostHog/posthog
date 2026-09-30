import { describe, expect, it } from "vitest";
import {
  classifySessionStartError,
  readSessionStartupPhase,
} from "./sessionStartup";

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

describe("classifySessionStartError", () => {
  it.each([
    {
      message: "Session initialization timed out after 30000ms",
      expected: {
        failure_reason: "startup_timeout",
        startup_step: "initialization",
      },
    },
    {
      message: "Session resumption timed out after 30000ms",
      expected: {
        failure_reason: "startup_timeout",
        startup_step: "resumption",
      },
    },
    {
      message: "Session setup hooks timed out after 600000ms",
      expected: {
        failure_reason: "startup_timeout",
        startup_step: "setup hooks",
      },
    },
    {
      message: "Session model switch failed: query closed",
      expected: {
        failure_reason: "startup_failed",
        startup_step: "model switch",
      },
    },
    {
      message: "Session effort update failed",
      expected: {
        failure_reason: "startup_failed",
        startup_step: "effort update",
      },
    },
    {
      message: "Session /Users/example/repo timed out after 5ms",
      expected: { failure_reason: "other" },
    },
    {
      message: "spawn claude ENOENT",
      expected: { failure_reason: "other" },
    },
  ])("classifies $message", ({ message, expected }) => {
    expect(classifySessionStartError(message)).toEqual(expected);
  });
});
