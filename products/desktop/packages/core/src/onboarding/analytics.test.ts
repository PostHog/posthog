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
      stepId: "select-repo",
      stepIndex: 4,
      totalSteps: 5,
      stepEnteredAtMs: 1000,
      nowMs: 6000,
      context: { github_connected: true },
    });
    expect(props).toEqual({
      step_id: "select-repo",
      step_index: 4,
      total_steps: 5,
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
        repoSkipped: false,
      }),
    ).toEqual({
      duration_seconds: 10,
      github_connected: true,
      repo_skipped: false,
    });
  });
});

describe("buildAbandonedProps", () => {
  it("captures the last step and duration", () => {
    expect(
      buildAbandonedProps({
        lastStepId: "welcome",
        flowStartedAtMs: 0,
        nowMs: 2000,
      }),
    ).toEqual({ last_step_id: "welcome", duration_seconds: 2 });
  });
});
