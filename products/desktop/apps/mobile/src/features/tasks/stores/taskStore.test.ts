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
      name: "run after local edit",
      run: "2026-08-11T10:00:00Z",
      local: "2026-08-11T09:00:00Z",
      expected: true,
    },
    {
      name: "run before local edit",
      run: "2026-08-11T08:00:00Z",
      local: "2026-08-11T09:00:00Z",
      expected: false,
    },
    {
      name: "legacy local config without timestamp counts as stale",
      run: "2026-08-11T08:00:00Z",
      local: undefined,
      expected: true,
    },
    { name: "no run", run: undefined, local: undefined, expected: false },
    {
      name: "unparseable run timestamp",
      run: "not-a-date",
      local: "2026-08-11T09:00:00Z",
      expected: false,
    },
  ])("$name -> $expected", ({ run, local, expected }) => {
    expect(isRunConfigNewer(run, local)).toBe(expected);
  });
});

describe("setComposerConfig", () => {
  it("stamps updatedAt on every write", () => {
    useTaskStore.getState().setComposerConfig("task-1", { model: "opus" });

    const saved = useTaskStore.getState().composerConfigByTaskId["task-1"];
    expect(saved.model).toBe("opus");
    expect(Date.parse(saved.updatedAt ?? "")).not.toBeNaN();
  });
});
