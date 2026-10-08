import * as fs from "node:fs";
import * as os from "node:os";
import * as path from "node:path";
import { afterEach, beforeEach, describe, expect, it } from "vitest";
import type { RunStatus } from "./lifecycle";
import {
  appendEvent,
  createRunId,
  endRun,
  runDirectory,
  startRun,
  transcriptPath,
  writeTranscript,
} from "./lifecycle";

function readStatusFile(runId: string): RunStatus {
  return JSON.parse(
    fs.readFileSync(path.join(runDirectory(runId), "status.json"), "utf-8"),
  ) as RunStatus;
}

describe("lifecycle", () => {
  let originalHome: string | undefined;
  let tmpHome: string;

  beforeEach(() => {
    originalHome = process.env.HOME;
    tmpHome = fs.mkdtempSync(
      path.join(os.tmpdir(), "posthog-subagent-lifecycle-"),
    );
    process.env.HOME = tmpHome;
  });

  afterEach(() => {
    process.env.HOME = originalHome;
    fs.rmSync(tmpHome, { recursive: true, force: true });
  });

  it("createRunId returns distinct ids", () => {
    expect(createRunId()).not.toBe(createRunId());
  });

  it("startRun writes an initial 'running' status and a 'started' event", () => {
    const runId = createRunId();
    const status = startRun({ runId, mode: "single", agents: ["scout"] });
    expect(status.state).toBe("running");
    expect(status.lifecycleArtifactVersion).toBe(1);

    expect(readStatusFile(runId)).toMatchObject({
      runId,
      mode: "single",
      agents: ["scout"],
      state: "running",
    });

    const events = fs
      .readFileSync(path.join(runDirectory(runId), "events.jsonl"), "utf-8")
      .trim()
      .split("\n")
      .map((line) => JSON.parse(line));
    expect(events).toHaveLength(1);
    expect(events[0].type).toBe("started");
  });

  it("endRun transitions state and records durationMs + extra fields", () => {
    const runId = createRunId();
    const status = startRun({
      runId,
      mode: "parallel",
      agents: ["scout", "reviewer"],
    });
    const final = endRun(status, "completed", undefined, {
      totalTokens: 123,
      totalCost: 0.5,
      model: "anthropic/opus",
    });

    expect(final.state).toBe("completed");
    expect(final.durationMs).toBeGreaterThanOrEqual(0);
    expect(final.totalTokens).toBe(123);
    expect(final.totalCost).toBe(0.5);
    expect(readStatusFile(runId).state).toBe("completed");
  });

  it("endRun records an error message for failed runs", () => {
    const runId = createRunId();
    const status = startRun({ runId, mode: "single", agents: ["scout"] });
    const final = endRun(status, "failed", "boom");
    expect(final.state).toBe("failed");
    expect(final.error).toBe("boom");
  });

  it("appendEvent appends additional lines without clobbering earlier ones", () => {
    const runId = createRunId();
    startRun({ runId, mode: "single", agents: ["scout"] });
    appendEvent(runId, {
      type: "progress",
      timestamp: Date.now(),
      note: "halfway",
    });

    const events = fs
      .readFileSync(path.join(runDirectory(runId), "events.jsonl"), "utf-8")
      .trim()
      .split("\n");
    expect(events).toHaveLength(2);
  });

  it("writeTranscript stores content readable at transcriptPath", () => {
    const runId = createRunId();
    writeTranscript(runId, "# hello\n\nsome transcript content");
    expect(fs.readFileSync(transcriptPath(runId), "utf-8")).toBe(
      "# hello\n\nsome transcript content",
    );
  });

  it("writeTranscript truncates content exceeding maxBytes and appends a notice", () => {
    const runId = createRunId();
    writeTranscript(runId, "x".repeat(1000), 100);
    const stored = fs.readFileSync(transcriptPath(runId), "utf-8");
    expect(Buffer.byteLength(stored, "utf-8")).toBeLessThan(1000);
    expect(stored).toMatch(/transcript truncated: exceeded 100 bytes/);
  });
});
