import type { TaskRunStatus } from "@posthog/shared/domain-types";
import { describe, expect, it } from "vitest";
import type { TaskData } from "./sidebarData.types";
import { isTaskActivelyRunning } from "./taskRunning";

const task = (overrides: Partial<TaskData>): TaskData => ({
  id: "t",
  title: "t",
  createdAt: 0,
  lastActivityAt: 0,
  isGenerating: false,
  isUnread: false,
  isPinned: false,
  needsPermission: false,
  repository: null,
  isSuspended: false,
  folderPath: null,
  cloudPrUrl: null,
  branchName: null,
  linkedBranch: null,
  ...overrides,
});

describe("isTaskActivelyRunning", () => {
  it.each<{
    name: string;
    environment: "local" | "cloud" | undefined;
    status: TaskRunStatus | undefined;
    isGenerating: boolean;
    expected: boolean;
  }>([
    // The regression: local runs stay "in_progress" forever, so this must NOT
    // count as running or the warning fires on every local task ever run.
    {
      name: "stale local in_progress with no live prompt",
      environment: "local",
      status: "in_progress",
      isGenerating: false,
      expected: false,
    },
    {
      name: "local run with a prompt in flight",
      environment: "local",
      status: "in_progress",
      isGenerating: true,
      expected: true,
    },
    {
      name: "finished local run",
      environment: "local",
      status: "completed",
      isGenerating: false,
      expected: false,
    },
    {
      name: "idle local task that never ran",
      environment: "local",
      status: undefined,
      isGenerating: false,
      expected: false,
    },
    {
      name: "cloud run in progress",
      environment: "cloud",
      status: "in_progress",
      isGenerating: false,
      expected: true,
    },
    {
      name: "queued cloud run",
      environment: "cloud",
      status: "queued",
      isGenerating: false,
      expected: true,
    },
    {
      name: "not-started cloud run",
      environment: "cloud",
      status: "not_started",
      isGenerating: false,
      expected: true,
    },
    {
      name: "completed cloud run",
      environment: "cloud",
      status: "completed",
      isGenerating: false,
      expected: false,
    },
    {
      name: "failed cloud run",
      environment: "cloud",
      status: "failed",
      isGenerating: false,
      expected: false,
    },
    {
      name: "cancelled cloud run",
      environment: "cloud",
      status: "cancelled",
      isGenerating: false,
      expected: false,
    },
    {
      name: "cloud run generating",
      environment: "cloud",
      status: "in_progress",
      isGenerating: true,
      expected: true,
    },
    {
      name: "unknown environment with stale in_progress status",
      environment: undefined,
      status: "in_progress",
      isGenerating: false,
      expected: false,
    },
    {
      name: "generating before any run environment is recorded",
      environment: undefined,
      status: undefined,
      isGenerating: true,
      expected: true,
    },
  ])(
    "$name -> $expected",
    ({ environment, status, isGenerating, expected }) => {
      expect(
        isTaskActivelyRunning(
          task({
            taskRunEnvironment: environment,
            taskRunStatus: status,
            isGenerating,
          }),
        ),
      ).toBe(expected);
    },
  );
});
