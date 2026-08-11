import type { TaskRunEnvironment, TaskRunStatus } from "@posthog/shared";
import { describe, expect, it } from "vitest";
import {
  classifyTaskRunPlacement,
  getLocalRunState,
  isLocalRunTask,
  type TaskRunPlacement,
} from "./taskRunPlacement";

function task(environment: TaskRunEnvironment, status: TaskRunStatus) {
  return { latest_run: { environment, status } };
}

describe("classifyTaskRunPlacement", () => {
  it.each<[string, Parameters<typeof classifyTaskRunPlacement>[0]]>([
    ["a cloud run", task("cloud", "in_progress")],
    ["a run with no environment", { latest_run: { status: "completed" } }],
    ["a task with no run", {}],
    ["a task with a null run", { latest_run: null }],
    ["no task at all", undefined],
  ])("classifies %s as cloud", (_label, input) => {
    expect(classifyTaskRunPlacement(input)).toBe("cloud");
  });

  it.each<[TaskRunStatus, TaskRunPlacement]>([
    ["completed", "local-terminal"],
    ["failed", "local-terminal"],
    ["cancelled", "local-terminal"],
    ["in_progress", "local-active"],
    ["queued", "local-active"],
    ["not_started", "local-active"],
  ])("classifies a local %s run as %s", (status, expected) => {
    expect(classifyTaskRunPlacement(task("local", status))).toBe(expected);
  });
});

describe("isLocalRunTask", () => {
  it.each<[string, Parameters<typeof isLocalRunTask>[0], boolean]>([
    ["a finished local run", task("local", "completed"), true],
    ["a live local run", task("local", "in_progress"), true],
    ["a cloud run", task("cloud", "completed"), false],
    ["no run", {}, false],
  ])("returns %s -> %s", (_label, input, expected) => {
    expect(isLocalRunTask(input)).toBe(expected);
  });
});

describe("getLocalRunState", () => {
  it("leaves cloud tasks alone — no notice, real composer", () => {
    expect(getLocalRunState("cloud")).toBeNull();
  });

  it("offers to continue a finished desktop run in the cloud", () => {
    expect(getLocalRunState("local-terminal")).toEqual({
      notice: "This task last ran on your desktop",
      actionLabel: "Continue in cloud",
      canContinue: true,
    });
  });

  it("disables the action while the desktop run is still going", () => {
    expect(getLocalRunState("local-active")).toEqual({
      notice: "This task is running on your desktop",
      actionLabel: "Running on desktop…",
      canContinue: false,
    });
  });

  it("replaces the composer exactly when a desktop run owns the task", () => {
    const placements: TaskRunPlacement[] = [
      "cloud",
      "local-active",
      "local-terminal",
    ];
    for (const placement of placements) {
      expect(getLocalRunState(placement) === null).toBe(
        classifyTaskRunPlacement({
          latest_run: {
            environment: placement === "cloud" ? "cloud" : "local",
            status: placement === "local-active" ? "in_progress" : "completed",
          },
        }) === "cloud",
      );
    }
  });
});
