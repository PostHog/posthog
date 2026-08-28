import { expect, it } from "vitest";
import {
  type BuilderRunSummary,
  FRESH_SESSION_GRACE_MS,
  isBuilderSessionEnded,
} from "./loopBuilderLiveness";
import type { LoopBuilderSession } from "./loopBuilderSessionStore";

const NOW = 1_752_000_000_000;

function session(ageMs: number): LoopBuilderSession {
  return {
    taskId: "task-1",
    prompt: "prompt",
    startedAt: NOW - ageMs,
    identity: "us:1",
  };
}

function summaries(
  run: BuilderRunSummary | null | undefined,
): Map<string, BuilderRunSummary | null> {
  const map = new Map<string, BuilderRunSummary | null>();
  if (run !== undefined) map.set("task-1", run);
  return map;
}

const WITHIN_GRACE = FRESH_SESSION_GRACE_MS - 1_000;
const PAST_GRACE = FRESH_SESSION_GRACE_MS + 1_000;

it.each([
  {
    name: "unknown task within grace stays",
    ageMs: WITHIN_GRACE,
    run: undefined,
    ended: false,
  },
  {
    name: "unknown task past grace is ended",
    ageMs: PAST_GRACE,
    run: undefined,
    ended: true,
  },
  {
    name: "runless task within grace stays",
    ageMs: WITHIN_GRACE,
    run: null,
    ended: false,
  },
  {
    name: "runless task past grace is ended",
    ageMs: PAST_GRACE,
    run: null,
    ended: true,
  },
  {
    name: "running cloud run stays even past grace",
    ageMs: PAST_GRACE,
    run: { environment: "cloud", status: "in_progress" },
    ended: false,
  },
  {
    name: "queued cloud run stays",
    ageMs: PAST_GRACE,
    run: { environment: "cloud", status: "queued" },
    ended: false,
  },
  {
    name: "statusless cloud run stays",
    ageMs: PAST_GRACE,
    run: { environment: "cloud", status: null },
    ended: false,
  },
  {
    name: "completed run is ended even within grace",
    ageMs: WITHIN_GRACE,
    run: { environment: "cloud", status: "completed" },
    ended: true,
  },
  {
    name: "failed run is ended even within grace",
    ageMs: WITHIN_GRACE,
    run: { environment: "cloud", status: "failed" },
    ended: true,
  },
  {
    name: "cancelled run is ended even within grace",
    ageMs: WITHIN_GRACE,
    run: { environment: "cloud", status: "cancelled" },
    ended: true,
  },
  {
    name: "non-cloud run is ended",
    ageMs: WITHIN_GRACE,
    run: { environment: "local", status: "in_progress" },
    ended: true,
  },
])("$name", ({ ageMs, run, ended }) => {
  expect(
    isBuilderSessionEnded(session(ageMs), summaries(run), new Set(), NOW),
  ).toBe(ended);
});

it("archived task is ended regardless of a live run", () => {
  expect(
    isBuilderSessionEnded(
      session(WITHIN_GRACE),
      summaries({ environment: "cloud", status: "in_progress" }),
      new Set(["task-1"]),
      NOW,
    ),
  ).toBe(true);
});
