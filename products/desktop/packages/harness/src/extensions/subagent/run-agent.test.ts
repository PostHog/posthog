import * as fs from "node:fs";
import * as os from "node:os";
import * as path from "node:path";
import type { Api, Model } from "@earendil-works/pi-ai";
import type { ExtensionContext } from "@earendil-works/pi-coding-agent";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const { spawnChildProcessMock } = vi.hoisted(() => ({
  spawnChildProcessMock: vi.fn(),
}));
vi.mock("./process/child-process", () => ({
  spawnChildProcess: spawnChildProcessMock,
}));

import type { AgentConfig } from "./agents";
import type { RunStatus } from "./lifecycle";
import { runDirectory, transcriptPath } from "./lifecycle";
import { runAgent } from "./run-agent";

function readStatus(runId: string): RunStatus | undefined {
  try {
    return JSON.parse(
      fs.readFileSync(path.join(runDirectory(runId), "status.json"), "utf-8"),
    ) as RunStatus;
  } catch {
    return undefined;
  }
}

function readTranscript(runId: string): string | undefined {
  try {
    return fs.readFileSync(transcriptPath(runId), "utf-8");
  } catch {
    return undefined;
  }
}

function makeModel(): Model<Api> {
  return {
    id: "sonnet",
    name: "Sonnet",
    api: "anthropic-messages",
    provider: "anthropic",
    baseUrl: "https://api.anthropic.com",
    reasoning: false,
    input: ["text"],
    cost: { input: 0, output: 0, cacheRead: 0, cacheWrite: 0 },
    contextWindow: 200000,
    maxTokens: 8192,
  } as Model<Api>;
}

function makeCtx(cwd: string): ExtensionContext {
  const model = makeModel();
  return {
    cwd,
    model,
    isProjectTrusted: () => false,
    sessionManager: { getBranch: () => [] },
    modelRegistry: {
      find: () => model,
      getAll: () => [model],
      getApiKeyAndHeaders: async () => ({ ok: true, apiKey: "test-key" }),
    },
  } as unknown as ExtensionContext;
}

const agent: AgentConfig = {
  name: "scout",
  description: "test agent",
  systemPrompt: "be a scout",
  source: "bundled",
};

describe("runAgent lifecycle persistence", () => {
  let originalHome: string | undefined;
  let tmpHome: string;

  beforeEach(() => {
    originalHome = process.env.HOME;
    tmpHome = fs.mkdtempSync(
      path.join(os.tmpdir(), "posthog-subagent-run-agent-"),
    );
    process.env.HOME = tmpHome;
    spawnChildProcessMock.mockReset();
  });

  afterEach(() => {
    process.env.HOME = originalHome;
    fs.rmSync(tmpHome, { recursive: true, force: true });
  });

  it("writes its own status.json (completed) and transcript.md for a successful run", async () => {
    spawnChildProcessMock.mockImplementation(
      ({ onStdoutLine }: { onStdoutLine: (line: string) => void }) => {
        const message = {
          role: "assistant",
          content: [{ type: "text", text: "found the bug" }],
          usage: {
            input: 10,
            output: 5,
            cacheRead: 0,
            cacheWrite: 0,
            totalTokens: 15,
            cost: { total: 0.001 },
          },
          stopReason: "end",
        };
        onStdoutLine(JSON.stringify({ type: "message_end", message }));
        return { exited: Promise.resolve(0), kill: vi.fn() };
      },
    );

    const result = await runAgent({
      ctx: makeCtx("/repo"),
      agent,
      task: "find it",
    });

    expect(result.exitCode).toBe(0);

    const status = readStatus(result.runId);
    expect(status?.state).toBe("completed");
    expect(status?.model).toBe("anthropic/sonnet");
    expect(status?.mode).toBe("single");
    expect(status?.agents).toEqual(["scout"]);
    expect(status?.resultSummary).toContain("found the bug");

    const transcript = readTranscript(result.runId);
    expect(transcript).toContain("found the bug");
    expect(transcript).toContain(`runId: ${result.runId}`);
  });

  it("writes status.json (failed) with the error when auth resolution fails", async () => {
    const ctx = makeCtx("/repo");
    ctx.modelRegistry.getApiKeyAndHeaders = vi.fn(async () => ({
      ok: false,
      error: "no creds",
    }));

    const result = await runAgent({ ctx, agent, task: "find it" });

    expect(result.exitCode).toBe(1);
    expect(spawnChildProcessMock).not.toHaveBeenCalled();

    const status = readStatus(result.runId);
    expect(status?.state).toBe("failed");
    expect(status?.error).toMatch(/No credentials available/);
  });

  it("writes status.json (failed) when the child process exits non-zero", async () => {
    spawnChildProcessMock.mockReturnValue({
      exited: Promise.resolve(1),
      kill: vi.fn(),
    });

    const result = await runAgent({
      ctx: makeCtx("/repo"),
      agent,
      task: "find it",
    });

    expect(result.exitCode).toBe(1);
    expect(readStatus(result.runId)?.state).toBe("failed");
  });

  it("writes status.json (aborted) when the signal aborts", async () => {
    const controller = new AbortController();
    spawnChildProcessMock.mockImplementation(() => {
      controller.abort();
      return { exited: Promise.resolve(1), kill: vi.fn() };
    });

    const result = await runAgent({
      ctx: makeCtx("/repo"),
      agent,
      task: "find it",
      signal: controller.signal,
    });

    expect(result.stopReason).toBe("aborted");
    expect(readStatus(result.runId)?.state).toBe("aborted");
  });
});
