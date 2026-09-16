import { describe, expect, it } from "vitest";
import {
  buildAbandonedProps,
  buildCompletedProps,
  buildStepCompletedProps,
  durationSeconds,
} from "./analytics";

describe("durationSeconds", () => {
  it("rounds milliseconds to whole seconds", () => {
    expect(durationSeconds(1000, 4400)).toBe(3);
  });
});

describe("buildStepCompletedProps", () => {
  it("computes duration and merges context", () => {
    const props = buildStepCompletedProps({
      stepId: "install-cli",
      stepIndex: 3,
      totalSteps: 4,
      stepEnteredAtMs: 1000,
      nowMs: 6000,
      context: { github_connected: true },
    });
    expect(props).toEqual({
      step_id: "install-cli",
      step_index: 3,
      total_steps: 4,
      duration_seconds: 5,
      github_connected: true,
    });
  });
});

describe("buildCompletedProps", () => {
  it("shapes completion flags and duration", () => {
    expect(
      buildCompletedProps({
        flowStartedAtMs: 0,
        nowMs: 10000,
        githubConnected: true,
      }),
    ).toEqual({
      duration_seconds: 10,
      github_connected: true,
    });
  });
});

describe("buildAbandonedProps", () => {
  it("captures the last step and duration", () => {
    expect(
      buildAbandonedProps({
        lastStepId: "project-select",
        flowStartedAtMs: 0,
        nowMs: 2000,
      }),
    ).toEqual({ last_step_id: "project-select", duration_seconds: 2 });
  });
});
