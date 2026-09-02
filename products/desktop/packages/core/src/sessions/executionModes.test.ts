import { describe, expect, it } from "vitest";
import {
  getAvailableModesForAdapter,
  getDefaultExecutionModeForAdapter,
} from "./executionModes";

describe("getAvailableModesForAdapter", () => {
  it.each([
    ["claude", ["default", "acceptEdits", "plan", "bypassPermissions", "auto"]],
    ["codex", ["plan", "read-only", "auto", "full-access"]],
  ] as const)("returns %s execution modes", (adapter, expected) => {
    expect(getAvailableModesForAdapter(adapter).map((mode) => mode.id)).toEqual(
      expected,
    );
  });
});

describe("getDefaultExecutionModeForAdapter", () => {
  it.each([
    ["claude", "plan"],
    ["codex", "auto"],
  ] as const)("returns the desktop default for %s", (adapter, expected) => {
    expect(getDefaultExecutionModeForAdapter(adapter)).toBe(expected);
  });
});
