import { describe, expect, expectTypeOf, it } from "vitest";
import type {
  Task,
  TaskRun,
  TaskRunArtifact,
  TaskRunStatus,
} from "./domain-types";
import {
  type CloudPermissionOption,
  type CloudTaskUpdatePayload,
  isTerminalStatus,
  type Task as RootTask,
  type TaskRun as RootTaskRun,
  type TaskRunArtifact as RootTaskRunArtifact,
  type TaskRunStatus as RootTaskRunStatus,
  TERMINAL_STATUSES,
} from "./index";
import type {
  Task as LegacyTask,
  TaskRun as LegacyTaskRun,
  TaskRunArtifact as LegacyTaskRunArtifact,
  TaskRunStatus as LegacyTaskRunStatus,
} from "./task";

describe("cloud task contract exports", () => {
  it("keeps legacy and root task exports canonical", () => {
    expectTypeOf<LegacyTask>().toEqualTypeOf<Task>();
    expectTypeOf<LegacyTaskRun>().toEqualTypeOf<TaskRun>();
    expectTypeOf<LegacyTaskRunArtifact>().toEqualTypeOf<TaskRunArtifact>();
    expectTypeOf<LegacyTaskRunStatus>().toEqualTypeOf<TaskRunStatus>();
    expectTypeOf<RootTask>().toEqualTypeOf<Task>();
    expectTypeOf<RootTaskRun>().toEqualTypeOf<TaskRun>();
    expectTypeOf<RootTaskRunArtifact>().toEqualTypeOf<TaskRunArtifact>();
    expectTypeOf<RootTaskRunStatus>().toEqualTypeOf<TaskRunStatus>();
  });

  it("exports cloud permission and update payload contracts from the root", () => {
    expectTypeOf<CloudPermissionOption>().toMatchTypeOf<{
      kind: string;
      optionId: string;
      name: string;
    }>();
    expectTypeOf<CloudTaskUpdatePayload["kind"]>().toEqualTypeOf<
      "logs" | "status" | "snapshot" | "error" | "permission_request"
    >();
  });

  it("exports terminal status helpers from the root", () => {
    expect(TERMINAL_STATUSES).toEqual(["completed", "failed", "cancelled"]);
    expect(isTerminalStatus("completed")).toBe(true);
    expect(isTerminalStatus("in_progress")).toBe(false);
  });
});
