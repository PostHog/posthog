import { mkdir, mkdtemp, rm, writeFile } from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const reportAnalysisInsight = vi.fn();

vi.mock("../../../signed-commit-artefacts", () => ({
  createSandboxPosthogClient: () => ({ reportAnalysisInsight }),
  withReportDeadline: <T>(work: (signal: AbortSignal) => Promise<T>) =>
    work(new AbortController().signal),
}));

import { INSIGHTS_STATE_KEY, reportInsightTool } from "./report-insight";

const RUN_LOG = [
  JSON.stringify({
    type: "pi_event",
    event: {
      type: "tool_call_started",
      toolCall: {
        kind: "execute",
        title: "bash",
        rawInput: { command: "docker compose up -d postgres" },
      },
    },
  }),
  JSON.stringify({
    type: "pi_event",
    event: {
      type: "tool_call_updated",
      toolCall: {
        status: "failed",
        rawOutput: [
          {
            type: "text",
            text: 'connection to server at "localhost", port 5432 failed\nConnection refused',
          },
        ],
      },
    },
  }),
  '{"type":"pi_event","event":{"type":"tool_call_updated","toolCall":{"status":"failed","rawOutput":[{"type":"text","text":"ui:\\n\\u2009ERR_PNPM_RECURSIVE_EXEC_FIRST_FAIL\\u2009 Command \\"biome\\" not found\\n"}]}}}',
].join("\n");

const LOG_RELATIVE_PATH = ".posthog/attachments/run-1/art-1/run-log.jsonl";

function appendingUpdateMock(state: Record<string, unknown>) {
  return (_t: string, _r: string, insight: Record<string, unknown>) => {
    const current = state[INSIGHTS_STATE_KEY];
    const next = Array.isArray(current) ? [...current, insight] : [insight];
    state[INSIGHTS_STATE_KEY] = next;
    return Promise.resolve({ insight_index: next.length - 1 });
  };
}

function ctx(cwd: string) {
  return { cwd, taskId: "task-1", taskRunId: "run-1" };
}

function validFinding(overrides: Record<string, unknown> = {}) {
  return {
    observation:
      "The test suite was started three times; the first two attempts failed while the agent installed and started Postgres.",
    evidence: [
      {
        quote: "docker compose up -d postgres",
        evidence_type: "transcript_quote",
      },
    ],
    occurrence_count: 2,
    category: "environment_failure",
    wasted_effort: { tool_calls: 14, seconds: 210 },
    recurrence: "every_run_in_this_repo",
    confidence_basis: "directly_observed",
    suggested_fix: {
      change:
        "Have Postgres already running in this repo's sandbox before the agent starts working.",
      done_when:
        "The test suite passes on its first attempt in a fresh sandbox.",
      required_services: ["postgres"],
    },
    ...overrides,
  };
}

describe("reportInsightTool", () => {
  let cwd: string;

  beforeEach(async () => {
    vi.clearAllMocks();
    cwd = await mkdtemp(path.join(os.tmpdir(), "report-insight-"));
    const logPath = path.join(cwd, LOG_RELATIVE_PATH);
    await mkdir(path.dirname(logPath), { recursive: true });
    await writeFile(logPath, RUN_LOG);
    reportAnalysisInsight.mockResolvedValue({ insight_index: 0 });
  });

  afterEach(async () => {
    await rm(cwd, { recursive: true, force: true });
  });

  it("is gated to cloud task_analysis runs", () => {
    const meta = {
      environment: "cloud" as const,
      taskOriginProduct: "task_analysis",
    };
    expect(reportInsightTool.isEnabled(ctx(cwd), meta)).toBe(true);
    expect(
      reportInsightTool.isEnabled(ctx(cwd), {
        ...meta,
        taskOriginProduct: "user_created",
      }),
    ).toBe(false);
    expect(
      reportInsightTool.isEnabled(ctx(cwd), { ...meta, environment: "local" }),
    ).toBe(false);
  });

  it("persists a verified finding through the report endpoint", async () => {
    const result = await reportInsightTool.handler(ctx(cwd), validFinding());
    expect(result.isError).toBeUndefined();
    const saved = reportAnalysisInsight.mock.calls[0][2];
    expect(saved.category).toBe("environment_failure");
    expect(saved.observation).toBeDefined();
    expect(saved.schema_version).toBeUndefined();
    expect(saved.reported_at).toBeUndefined();
  });

  it("accepts a quote whose characters are stored as unicode escapes", async () => {
    const result = await reportInsightTool.handler(
      ctx(cwd),
      validFinding({
        evidence: [
          {
            quote:
              'ERR_PNPM_RECURSIVE_EXEC_FIRST_FAIL Command "biome" not found',
            evidence_type: "command_output",
          },
        ],
      }),
    );
    expect(result.isError).toBeUndefined();
  });

  it.each([
    [
      "quote not in transcript",
      validFinding({
        evidence: [
          {
            quote: "this text never appeared in the run at all",
            evidence_type: "transcript_quote",
          },
        ],
      }),
      /not found in the run log/,
    ],
    [
      "credential-like token in evidence",
      validFinding({
        evidence: [
          {
            quote: "docker compose up -d postgres",
            evidence_type: "transcript_quote",
          },
        ],
        suggested_fix: {
          change:
            "Provide the API token ghp_abcdefghijklmnopqrstuvwx to the sandbox before the run starts working.",
          done_when: "Tests pass on the first attempt in a fresh sandbox.",
        },
      }),
      /credential-like token/,
    ],
    [
      "other without justification",
      validFinding({ category: "other", wasted_effort: undefined }),
      /other_justification/,
    ],
    [
      "env var value smuggled in",
      validFinding({
        suggested_fix: {
          change:
            "Provide the database credentials to the sandbox before the test suite starts running.",
          done_when: "Tests pass on the first attempt in a fresh sandbox.",
          env_var_names: ["DATABASE_URL=postgres://secret"],
        },
      }),
      /names only/,
    ],
    [
      "bare credential in env_var_names",
      validFinding({
        suggested_fix: {
          change:
            "Provide the database credentials to the sandbox before the test suite starts running.",
          done_when: "Tests pass on the first attempt in a fresh sandbox.",
          env_var_names: ["ghp_abcdefghijklmnopqrstuvwx"],
        },
      }),
      /credential-like token/,
    ],
    [
      "credential in other_justification",
      validFinding({
        category: "other",
        other_justification:
          "The run stalled waiting on a token that was pasted inline as ghp_abcdefghijklmnopqrstuvwx by the caller.",
      }),
      /credential-like token/,
    ],
    [
      "finding combined with no_findings_reason",
      validFinding({ no_findings_reason: "run_was_efficient" }),
      /cannot be combined/,
    ],
  ])("rejects %s with a coaching error", async (_name, args, message) => {
    const result = await reportInsightTool.handler(ctx(cwd), args);
    expect(result.isError).toBe(true);
    expect(result.content[0].text).toMatch(message);
    expect(reportAnalysisInsight).not.toHaveBeenCalled();
  });

  it("numbers the recorded finding from the server's index", async () => {
    reportAnalysisInsight.mockResolvedValue({ insight_index: 2 });
    const result = await reportInsightTool.handler(ctx(cwd), validFinding());
    expect(result.isError).toBeUndefined();
    expect(result.content[0].text).toMatch(
      /Recorded finding 3 .+ 2 more allowed/,
    );
  });

  it("returns a coaching error when the server rejects the report", async () => {
    reportAnalysisInsight.mockRejectedValueOnce(
      new Error(
        'Failed request: [400] {"evidence":[{"quote":["Ensure this value has at least 20 characters."]}]}',
      ),
    );
    const result = await reportInsightTool.handler(ctx(cwd), validFinding());
    expect(result.isError).toBe(true);
    expect(result.content[0].text).toMatch(/was rejected by the server/);
    expect(result.content[0].text).toContain(
      "Ensure this value has at least 20 characters",
    );
  });

  it("accumulates findings filed as parallel tool calls", async () => {
    const state: Record<string, unknown> = {};
    reportAnalysisInsight.mockImplementation(appendingUpdateMock(state));

    const second = validFinding({
      observation:
        "The agent retried the signed commit against a repository it had no write access to, twice, before switching.",
      category: "wasted_retry",
    });
    const results = await Promise.all([
      reportInsightTool.handler(ctx(cwd), validFinding()),
      reportInsightTool.handler(ctx(cwd), second),
    ]);
    expect(results.every((result) => result.isError === undefined)).toBe(true);
    expect(state[INSIGHTS_STATE_KEY]).toHaveLength(2);
  });

  it("records a no-findings report once", async () => {
    const result = await reportInsightTool.handler(ctx(cwd), {
      no_findings_reason: "run_was_efficient",
    });
    expect(result.isError).toBeUndefined();
    expect(reportAnalysisInsight.mock.calls[0][2]).toEqual({
      no_findings_reason: "run_was_efficient",
    });
  });

  it("accepts a quote whose newlines are stored JSON-escaped in the log", async () => {
    const result = await reportInsightTool.handler(
      ctx(cwd),
      validFinding({
        evidence: [
          {
            quote: "port 5432 failed\nConnection refused",
            evidence_type: "command_output",
          },
        ],
      }),
    );
    expect(result.isError).toBeUndefined();
  });

  it("rejects a finding when no run log is attached", async () => {
    await rm(path.join(cwd, ".posthog"), { recursive: true, force: true });
    const result = await reportInsightTool.handler(ctx(cwd), validFinding());
    expect(result.isError).toBe(true);
    expect(result.content[0].text).toMatch(/No run log was found/);
  });
});
