import type { AgentSession } from "@posthog/shared";
import type { TaskRun, TaskRunStatus } from "@posthog/shared/domain-types";
import { describe, expect, it } from "vitest";
import {
  hasCanvasGenerationStarted,
  isCanvasGenerating,
  isCanvasGenerationRunning,
  resolveCanvasGenerationStatus,
} from "./canvasGenerationStatus";

type Run = Pick<TaskRun, "environment" | "status">;
type Session = Pick<AgentSession, "status" | "cloudStatus" | "isPromptPending">;
type GenSession = Session;

const genSession = (
  status: AgentSession["status"],
  opts?: { cloudStatus?: TaskRunStatus; isPromptPending?: boolean },
): GenSession => ({
  status,
  cloudStatus: opts?.cloudStatus,
  isPromptPending: opts?.isPromptPending ?? false,
});

const run = (environment: "local" | "cloud", status: TaskRunStatus): Run => ({
  environment,
  status,
});
const session = (
  status: AgentSession["status"],
  cloudStatus?: TaskRunStatus,
): Session => ({ status, cloudStatus, isPromptPending: false });

describe("isCanvasGenerationRunning", () => {
  it("is not running when there is no generation task", () => {
    expect(
      isCanvasGenerationRunning({
        genTaskId: null,
        genTaskLoading: false,
        latestRun: undefined,
        session: undefined,
      }),
    ).toBe(false);
  });

  it("assumes running while the task record is still loading", () => {
    expect(
      isCanvasGenerationRunning({
        genTaskId: "t1",
        genTaskLoading: true,
        latestRun: undefined,
        session: undefined,
      }),
    ).toBe(true);
  });

  it.each<[string, Run, Session | undefined, boolean]>([
    ["in_progress, no session", run("cloud", "in_progress"), undefined, true],
    [
      "session cloudStatus terminal overrides run record",
      run("cloud", "in_progress"),
      session("connected", "completed"),
      false,
    ],
    ["run record terminal", run("cloud", "failed"), undefined, false],
  ])("cloud: %s", (_label, latestRun, sess, expected) => {
    expect(
      isCanvasGenerationRunning({
        genTaskId: "t1",
        genTaskLoading: false,
        latestRun,
        session: sess,
      }),
    ).toBe(expected);
  });

  it("is running when loaded with no run record yet but a connected session", () => {
    // A task whose first run hasn't been created falls through to the local
    // path; isTerminalStatus(undefined) is false, so a live session decides.
    expect(
      isCanvasGenerationRunning({
        genTaskId: "t1",
        genTaskLoading: false,
        latestRun: undefined,
        session: session("connected"),
      }),
    ).toBe(true);
  });

  it.each<[string, Run, Session | undefined, boolean]>([
    [
      "session connected",
      run("local", "in_progress"),
      session("connected"),
      true,
    ],
    [
      "session connecting",
      run("local", "in_progress"),
      session("connecting"),
      true,
    ],
    ["no live session", run("local", "in_progress"), undefined, false],
    [
      "session disconnected",
      run("local", "in_progress"),
      session("disconnected"),
      false,
    ],
    // The regression: a terminal run record must stop "running" even if the
    // live session is still (stale) reporting connected — otherwise the canvas
    // is stranded on "Generating" forever.
    [
      "terminal run wins over stale connected session",
      run("local", "completed"),
      session("connected"),
      false,
    ],
    [
      "failed run wins over stale connected session",
      run("local", "failed"),
      session("connected"),
      false,
    ],
  ])("local: %s", (_label, latestRun, sess, expected) => {
    expect(
      isCanvasGenerationRunning({
        genTaskId: "t1",
        genTaskLoading: false,
        latestRun,
        session: sess,
      }),
    ).toBe(expected);
  });
});

describe("isCanvasGenerating", () => {
  it("is not generating without a task, and assumes generating while loading", () => {
    expect(
      isCanvasGenerating({
        genTaskId: null,
        genTaskLoading: false,
        latestRun: undefined,
        session: undefined,
      }),
    ).toBe(false);
    expect(
      isCanvasGenerating({
        genTaskId: "t1",
        genTaskLoading: true,
        latestRun: undefined,
        session: undefined,
      }),
    ).toBe(true);
  });

  it.each<[string, Run, GenSession | undefined, boolean]>([
    ["cloud in_progress", run("cloud", "in_progress"), undefined, true],
    [
      "cloud cloudStatus completed clears it",
      run("cloud", "in_progress"),
      genSession("connected", { cloudStatus: "completed" }),
      false,
    ],
    // Local: keys off the pending prompt, NOT the connection — a session that
    // lingers connected after the prompt finishes is no longer generating.
    [
      "local prompt pending",
      run("local", "in_progress"),
      genSession("connected", { isPromptPending: true }),
      true,
    ],
    [
      "local connected but prompt settled",
      run("local", "in_progress"),
      genSession("connected", { isPromptPending: false }),
      false,
    ],
    [
      "local still connecting",
      run("local", "in_progress"),
      genSession("connecting"),
      true,
    ],
    [
      "local terminal run record wins",
      run("local", "completed"),
      genSession("connected", { isPromptPending: true }),
      false,
    ],
  ])("%s", (_label, latestRun, sess, expected) => {
    expect(
      isCanvasGenerating({
        genTaskId: "t1",
        genTaskLoading: false,
        latestRun,
        session: sess,
      }),
    ).toBe(expected);
  });
});

describe("hasCanvasGenerationStarted", () => {
  it.each<[string, Run | undefined, GenSession | undefined, boolean]>([
    // The create→connect gap: task exists, no live session, not yet in_progress.
    ["not started yet", run("local", "queued"), undefined, false],
    [
      "local prompt pending",
      run("local", "queued"),
      genSession("connected", { isPromptPending: true }),
      true,
    ],
    [
      "local session connecting",
      run("local", "queued"),
      genSession("connecting"),
      true,
    ],
    ["run in_progress", run("local", "in_progress"), undefined, true],
    // A session that lingers connected after the prompt settled still counts as
    // started — it's the arming latch, not the running signal.
    [
      "local connected, prompt settled",
      run("local", "completed"),
      genSession("connected", { isPromptPending: false }),
      true,
    ],
    ["cloud in_progress", run("cloud", "in_progress"), undefined, true],
    ["cloud queued", run("cloud", "queued"), undefined, true],
    ["cloud not_started", run("cloud", "not_started"), undefined, false],
  ])("%s", (_label, latestRun, sess, expected) => {
    expect(hasCanvasGenerationStarted({ latestRun, session: sess })).toBe(
      expected,
    );
  });
});

describe("resolveCanvasGenerationStatus", () => {
  it.each<[string, Run | undefined, GenSession | undefined, string]>([
    ["local completed", run("local", "completed"), undefined, "completed"],
    ["local failed", run("local", "failed"), undefined, "failed"],
    ["local cancelled", run("local", "cancelled"), undefined, "cancelled"],
    // A local run that finished via the session before its record flipped
    // terminal still counts as a successful completion.
    [
      "local non-terminal record",
      run("local", "in_progress"),
      undefined,
      "completed",
    ],
    [
      "cloud reads cloudStatus first",
      run("cloud", "in_progress"),
      genSession("connected", { cloudStatus: "failed" }),
      "failed",
    ],
    [
      "cloud falls back to run record",
      run("cloud", "completed"),
      undefined,
      "completed",
    ],
  ])("%s", (_label, latestRun, sess, expected) => {
    expect(resolveCanvasGenerationStatus({ latestRun, session: sess })).toBe(
      expected,
    );
  });
});
