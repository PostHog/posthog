import { describe, expect, it, vi } from "vitest";

vi.mock("@react-native-async-storage/async-storage", () => ({
  default: {
    getItem: vi.fn(),
    setItem: vi.fn(),
    removeItem: vi.fn(),
  },
}));

import { isRunConfigNewer, useTaskStore } from "./taskStore";

describe("isRunConfigNewer", () => {
  it.each([
    {
      name: "a run the local pick has not seen",
      run: "run-2",
      seen: "run-1",
      expected: true,
    },
    {
      name: "the run the local pick was made against",
      run: "run-1",
      seen: "run-1",
      expected: false,
    },
    {
      name: "legacy local config without a seen run counts as stale",
      run: "run-1",
      seen: undefined,
      expected: true,
    },
    { name: "no run at all", run: undefined, seen: undefined, expected: false },
    { name: "null run id", run: null, seen: "run-1", expected: false },
  ])("$name -> $expected", ({ run, seen, expected }) => {
    expect(isRunConfigNewer(run, seen)).toBe(expected);
  });
});

describe("setComposerConfig", () => {
  it("merges partial updates without dropping the seen run id", () => {
    const { setComposerConfig } = useTaskStore.getState();
    setComposerConfig("task-1", { model: "opus", lastSeenRunId: "run-1" });
    setComposerConfig("task-1", { reasoning: "high" });

    expect(useTaskStore.getState().composerConfigByTaskId["task-1"]).toEqual({
      model: "opus",
      reasoning: "high",
      lastSeenRunId: "run-1",
    });
  });
});
