import { mkdir, mkdtemp, rm, writeFile } from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const reportAnalysisActivity = vi.fn();

vi.mock("../../../signed-commit-artefacts", () => ({
  createSandboxPosthogClient: () => ({ reportAnalysisActivity }),
  withReportDeadline: <T>(work: (signal: AbortSignal) => Promise<T>) =>
    work(new AbortController().signal),
}));

import { reportActivityTool } from "./report-activity";

function at(seconds: number): string {
  return new Date(Date.UTC(2026, 0, 1, 0, 0, seconds)).toISOString();
}

function piStart(seconds: number, id: string, command: string): string {
  return JSON.stringify({
    type: "pi_event",
    timestamp: at(seconds),
    event: {
      type: "tool_call_started",
      toolCall: { id, kind: "execute", title: "bash", rawInput: { command } },
    },
  });
}

function piUpdate(
  seconds: number,
  id: string,
  status: string,
  text: string,
): string {
  return JSON.stringify({
    type: "pi_event",
    timestamp: at(seconds),
    event: {
      type: "tool_call_updated",
      toolCall: { id, status, rawOutput: [{ type: "text", text }] },
    },
  });
}

function acpUpdate(
  seconds: number,
  sessionUpdate: string,
  fields: Record<string, unknown>,
): string {
  return JSON.stringify({
    type: "notification",
    timestamp: at(seconds),
    notification: {
      method: "session/update",
      params: { update: { sessionUpdate, ...fields } },
    },
  });
}

// Lines 1-4: a pi verify span with one failure. Lines 5-8: a Claude ACP span with a 5 minute
// gap. Lines 9-14: a Codex command (title only, no rawInput), a Read, and a Skill call.
const RUN_LOG = `${[
  piStart(0, "c1", "pytest posthog/test_a.py"),
  piUpdate(
    30,
    "c1",
    "failed",
    'connection to server at "localhost", port 5432 failed\nConnection refused',
  ),
  piStart(
    31,
    "c2",
    "docker compose up -d postgres && pytest posthog/test_a.py",
  ),
  piUpdate(90, "c2", "completed", "1 passed"),
  acpUpdate(100, "tool_call", {
    toolCallId: "t1",
    kind: "execute",
    title: "Check the open pull request",
    rawInput: {},
  }),
  acpUpdate(101, "tool_call_update", {
    toolCallId: "t1",
    kind: "execute",
    status: "failed",
    rawInput: { command: "gh pr view 12" },
    rawOutput: "gh: command not found",
  }),
  acpUpdate(420, "tool_call", {
    toolCallId: "t2",
    kind: "execute",
    rawInput: {},
  }),
  acpUpdate(421, "tool_call_update", {
    toolCallId: "t2",
    kind: "execute",
    status: "completed",
    rawInput: { command: "cat .agents/skills/writing-tests/SKILL.md" },
  }),
  acpUpdate(430, "tool_call", {
    toolCallId: "t3",
    kind: "execute",
    title: "grep -rn 'a|b; c' src && cat AGENTS.md",
    locations: [],
  }),
  acpUpdate(431, "tool_call_update", {
    toolCallId: "t3",
    status: "completed",
    rawOutput: "matched three lines",
  }),
  acpUpdate(440, "tool_call", {
    toolCallId: "t4",
    kind: "read",
    title: "Read /repo/CLAUDE.md",
    rawInput: { file_path: "/repo/CLAUDE.md" },
  }),
  acpUpdate(441, "tool_call_update", {
    toolCallId: "t4",
    status: "completed",
  }),
  acpUpdate(450, "tool_call", {
    toolCallId: "t5",
    kind: "other",
    title: "Skill: writing-tests",
    rawInput: { skill_name: "writing-tests" },
  }),
  acpUpdate(451, "tool_call_update", {
    toolCallId: "t5",
    status: "completed",
  }),
].join("\n")}\n`;

const LOG_RELATIVE_PATH = ".posthog/attachments/run-1/art-1/run-log.jsonl";

function ctx(cwd: string) {
  return { cwd, taskId: "task-1", taskRunId: "run-1" };
}

function verifyActivity(overrides: Record<string, unknown> = {}) {
  return {
    goal_kind: "verify",
    goal: "run the backend tests",
    outcome: "worked",
    blocker_kind: "service_down",
    blocker_name: "port 5432",
    repair: "docker compose up -d postgres",
    evidence: "port 5432 failed\nConnection refused",
    start_line: 1,
    end_line: 4,
    ...overrides,
  };
}

describe("reportActivityTool", () => {
  let cwd: string;

  beforeEach(async () => {
    vi.clearAllMocks();
    cwd = await mkdtemp(path.join(os.tmpdir(), "report-activity-"));
    const logPath = path.join(cwd, LOG_RELATIVE_PATH);
    await mkdir(path.dirname(logPath), { recursive: true });
    await writeFile(logPath, RUN_LOG);
    reportAnalysisActivity.mockResolvedValue({ activity_index: 0 });
  });

  afterEach(async () => {
    await rm(cwd, { recursive: true, force: true });
  });

  it("is gated to cloud task_analysis runs", () => {
    const meta = {
      environment: "cloud" as const,
      taskOriginProduct: "task_analysis",
    };
    expect(reportActivityTool.isEnabled(ctx(cwd), meta)).toBe(true);
    expect(
      reportActivityTool.isEnabled(ctx(cwd), {
        ...meta,
        taskOriginProduct: "user_created",
      }),
    ).toBe(false);
    expect(
      reportActivityTool.isEnabled(ctx(cwd), { ...meta, environment: "local" }),
    ).toBe(false);
  });

  it("computes the pi span's metrics from its lines and stores the model fields", async () => {
    const result = await reportActivityTool.handler(ctx(cwd), verifyActivity());
    expect(result.isError).toBeUndefined();
    const saved = reportAnalysisActivity.mock.calls[0][2];
    expect(saved).toMatchObject({
      goal_kind: "verify",
      blocker_kind: "service_down",
      blocker_name: "port 5432",
      start_line: 1,
      end_line: 4,
      tool_calls: 2,
      failed_calls: 1,
      seconds: 90,
      idle_seconds: 0,
      commands: ["pytest", "docker compose", "pytest"],
      guidance_read: [],
    });
    expect(saved.schema_version).toBeUndefined();
  });

  it("computes the ACP span's metrics from the last timestamp before it, including idle time", async () => {
    const result = await reportActivityTool.handler(ctx(cwd), {
      goal_kind: "ship",
      goal: "inspect the open pull request",
      outcome: "failed",
      blocker_kind: "missing_binary",
      blocker_name: "gh",
      evidence: "gh: command not found",
      start_line: 5,
      end_line: 8,
    });
    expect(result.isError).toBeUndefined();
    expect(reportAnalysisActivity.mock.calls[0][2]).toMatchObject({
      tool_calls: 2,
      failed_calls: 1,
      seconds: 331,
      idle_seconds: 319,
      commands: ["gh pr", "cat"],
      guidance_read: [".agents/skills/writing-tests"],
    });
  });

  it("reads Codex title commands, Read paths, and Skill calls as commands and guidance", async () => {
    const result = await reportActivityTool.handler(ctx(cwd), {
      goal_kind: "orient",
      goal: "read the repository guidance",
      outcome: "worked",
      evidence: "Skill: writing-tests",
      start_line: 9,
      end_line: 14,
    });
    expect(result.isError).toBeUndefined();
    expect(reportAnalysisActivity.mock.calls[0][2]).toMatchObject({
      tool_calls: 3,
      failed_calls: 0,
      seconds: 30,
      commands: ["grep", "cat"],
      guidance_read: ["AGENTS.md", "CLAUDE.md", "skill:writing-tests"],
    });
  });

  it("counts only calls that started inside the range", async () => {
    const result = await reportActivityTool.handler(ctx(cwd), {
      goal_kind: "setup_env",
      goal: "start postgres",
      outcome: "worked",
      evidence: "docker compose up -d postgres",
      start_line: 2,
      end_line: 4,
    });
    expect(result.isError).toBeUndefined();
    expect(reportAnalysisActivity.mock.calls[0][2]).toMatchObject({
      tool_calls: 1,
      failed_calls: 0,
      seconds: 90,
    });
  });

  it("rejects a range that overlaps an activity it already recorded", async () => {
    const first = await reportActivityTool.handler(ctx(cwd), verifyActivity());
    expect(first.isError).toBeUndefined();
    const second = await reportActivityTool.handler(
      ctx(cwd),
      verifyActivity({ start_line: 3, end_line: 6 }),
    );
    expect(second.isError).toBe(true);
    expect(second.content[0].text).toMatch(
      /Activity 1 already covers lines 1-4.*start this one at line 5/,
    );
    expect(reportAnalysisActivity).toHaveBeenCalledTimes(1);
  });

  it.each([
    [
      "evidence outside the line range",
      verifyActivity({
        evidence: "gh: command not found",
        blocker_kind: undefined,
        blocker_name: undefined,
        repair: undefined,
      }),
      /not found in log lines 1-4/,
    ],
    [
      "evidence not in the log",
      verifyActivity({
        evidence: "this text never appeared in the run",
        blocker_kind: undefined,
        blocker_name: undefined,
        repair: undefined,
      }),
      /not found in log lines/,
    ],
    [
      "blocker_kind without blocker_name",
      verifyActivity({ blocker_name: undefined }),
      /requires blocker_name/,
    ],
    [
      "blocker_name missing from evidence",
      verifyActivity({ blocker_name: "postgres" }),
      /evidence must contain blocker_name/,
    ],
    [
      "blocker_name only as a substring of the evidence",
      verifyActivity({ blocker_name: "543" }),
      /evidence must contain blocker_name as a whole word/,
    ],
    [
      "repair without blocker_kind",
      verifyActivity({ blocker_kind: undefined, blocker_name: undefined }),
      /repair requires blocker_kind/,
    ],
    [
      "end_line before start_line",
      verifyActivity({ end_line: 1, start_line: 3 }),
      /end_line must not be before start_line/,
    ],
    [
      "end_line past the end of the log",
      verifyActivity({ start_line: 13, end_line: 15 }),
      /end_line 15 is past the end of the log \(14 lines\)/,
    ],
    [
      "credential-like token in repair",
      verifyActivity({
        repair:
          "export GH_TOKEN=ghp_abcdefghijklmnopqrstuvwx && gh auth status",
      }),
      /credential-like token/,
    ],
    [
      "GitHub app token in repair",
      verifyActivity({
        repair: "use ghs_abcdefghijklmnopqrstuvwx for the API call",
      }),
      /credential-like token/,
    ],
  ])("rejects %s with a coaching error", async (_name, args, message) => {
    const result = await reportActivityTool.handler(ctx(cwd), args);
    expect(result.isError).toBe(true);
    expect(result.content[0].text).toMatch(message);
    expect(reportAnalysisActivity).not.toHaveBeenCalled();
  });

  it("numbers the recorded activity from the server's index", async () => {
    reportAnalysisActivity.mockResolvedValue({ activity_index: 2 });
    const result = await reportActivityTool.handler(ctx(cwd), verifyActivity());
    expect(result.isError).toBeUndefined();
    expect(result.content[0].text).toMatch(
      /Recorded activity 3 .+ lines 1-4 of 14.+ 9 more allowed/,
    );
  });

  it("returns a coaching error when the server rejects the report", async () => {
    reportAnalysisActivity.mockRejectedValueOnce(
      new Error(
        'Failed request: [400] {"goal":["Ensure this field has no more than 80 characters."]}',
      ),
    );
    const result = await reportActivityTool.handler(ctx(cwd), verifyActivity());
    expect(result.isError).toBe(true);
    expect(result.content[0].text).toMatch(/was rejected by the server/);
    expect(result.content[0].text).toContain(
      "Ensure this field has no more than 80 characters",
    );
  });

  it("tells the model to retry when the report times out", async () => {
    reportAnalysisActivity.mockRejectedValueOnce(
      new Error("activity report timed out after 15000ms"),
    );
    const result = await reportActivityTool.handler(ctx(cwd), verifyActivity());
    expect(result.isError).toBe(true);
    expect(result.content[0].text).toMatch(
      /did not complete .*timed out.*same arguments/,
    );
  });

  it("rejects an activity when no run log is attached", async () => {
    await rm(path.join(cwd, ".posthog"), { recursive: true, force: true });
    const result = await reportActivityTool.handler(ctx(cwd), verifyActivity());
    expect(result.isError).toBe(true);
    expect(result.content[0].text).toMatch(/No run log was found/);
  });
});
