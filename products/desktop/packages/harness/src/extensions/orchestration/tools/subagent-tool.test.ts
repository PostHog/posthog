import { mkdirSync, mkdtempSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";
import { createPiToolCallRecord } from "@posthog/shared";
import { beforeEach, describe, expect, it, vi } from "vitest";

const { runAgentMock } = vi.hoisted(() => ({
  runAgentMock: vi.fn(),
}));

vi.mock("../run-agent", async () => {
  const actual =
    await vi.importActual<typeof import("../run-agent")>("../run-agent");
  return { ...actual, runAgent: runAgentMock };
});

import type { SingleRunResult } from "../run-agent";
import { __resetOrchestrationForTesting } from "../ui/status-registry";
import { registerSubagentTool } from "./subagent-tool";

function successResult(
  overrides: Partial<SingleRunResult> = {},
): SingleRunResult {
  return {
    runId: "test-run-id",
    startedAt: Date.now(),
    agent: "Explore",
    task: "look around",
    state: "completed",
    messages: [
      { role: "assistant", content: [{ type: "text", text: "done" }] } as never,
    ],
    usage: {
      input: 0,
      output: 0,
      cacheRead: 0,
      cacheWrite: 0,
      cost: 0,
      contextTokens: 0,
      turns: 1,
    },
    ...overrides,
  };
}

async function getExecute() {
  let registered:
    | { execute: (...args: unknown[]) => Promise<unknown> }
    | undefined;
  const pi = {
    registerTool: (tool: {
      execute: (...args: unknown[]) => Promise<unknown>;
    }) => {
      registered = tool;
    },
    registerCommand: () => {},
    on: () => {},
    events: { on: () => {}, emit: () => {} },
  } as unknown as ExtensionAPI;
  registerSubagentTool(pi);
  if (!registered) throw new Error("subagent tool was not registered");
  return registered.execute;
}

const fakeCtx = {
  cwd: "/repo",
  hasUI: true,
  isProjectTrusted: () => true,
  ui: { confirm: async () => true, input: vi.fn(async () => "human reply") },
};

describe("subagent tool", () => {
  beforeEach(() => {
    runAgentMock.mockReset();
    __resetOrchestrationForTesting();
  });

  it("errors when neither single nor parallel params are provided", async () => {
    const execute = await getExecute();
    const result = (await execute("id", {}, undefined, undefined, fakeCtx)) as {
      isError?: boolean;
      content: Array<{ text: string }>;
    };
    expect(result.isError).toBe(true);
    expect(result.content[0].text).toMatch(/Provide agent and task/);
    expect(runAgentMock).not.toHaveBeenCalled();
  });

  it("runs parallel tasks when top-level single-task fields are also present", async () => {
    runAgentMock.mockResolvedValue(successResult());
    const execute = await getExecute();
    const result = (await execute(
      "id",
      {
        agent: "Explore",
        task: "x",
        description: "Ignored task",
        tasks: [
          {
            agent: "Explore",
            task: "y",
            description: "Listing root files",
          },
        ],
      },
      undefined,
      undefined,
      fakeCtx,
    )) as { isError?: boolean };

    expect(result.isError).toBeUndefined();
    expect(runAgentMock).toHaveBeenCalledWith(
      expect.objectContaining({
        task: "y",
        description: "Listing root files",
      }),
    );
  });

  it("errors on an unknown agent name in single mode", async () => {
    const execute = await getExecute();
    const result = (await execute(
      "id",
      { agent: "not-real", task: "x" },
      undefined,
      undefined,
      fakeCtx,
    )) as {
      isError?: boolean;
      content: Array<{ text: string }>;
    };
    expect(result.isError).toBe(true);
    expect(result.content[0].text).toMatch(/Unknown agent/);
  });

  it("errors when parallel tasks exceed the max count", async () => {
    const execute = await getExecute();
    const tasks = Array.from({ length: 5 }, () => ({
      agent: "Explore",
      task: "x",
    }));
    const result = (await execute(
      "id",
      { tasks },
      undefined,
      undefined,
      fakeCtx,
    )) as {
      isError?: boolean;
      content: Array<{ text: string }>;
    };
    expect(result.isError).toBe(true);
    expect(result.content[0].text).toMatch(/Too many parallel tasks/);
    expect(runAgentMock).not.toHaveBeenCalled();
  });

  it("errors on an unknown agent name in a parallel task", async () => {
    const execute = await getExecute();
    const result = (await execute(
      "id",
      {
        tasks: [
          { agent: "Explore", task: "x" },
          { agent: "not-real", task: "y" },
        ],
      },
      undefined,
      undefined,
      fakeCtx,
    )) as { isError?: boolean; content: Array<{ text: string }> };
    expect(result.isError).toBe(true);
    expect(result.content[0].text).toMatch(/Unknown agent/);
    expect(runAgentMock).not.toHaveBeenCalled();
  });

  it("dispatches single mode to runAgent and streams its state", async () => {
    const activeResult = successResult({ state: "running" });
    runAgentMock.mockImplementation(
      async ({
        description,
        onUpdate,
      }: {
        description?: string;
        onUpdate: (result: SingleRunResult) => void;
      }) => {
        onUpdate({ ...activeResult, description });
        return successResult({ description });
      },
    );
    const onUpdate = vi.fn();
    const execute = await getExecute();
    const result = (await execute(
      "id",
      {
        agent: "Explore",
        task: "find auth code",
        description: "Finding auth code",
      },
      undefined,
      onUpdate,
      fakeCtx,
    )) as {
      isError?: boolean;
      content: Array<{ text: string }>;
      details: { results: SingleRunResult[] };
    };
    expect(runAgentMock).toHaveBeenCalledTimes(1);
    expect(runAgentMock).toHaveBeenCalledWith(
      expect.objectContaining({ description: "Finding auth code" }),
    );
    expect(onUpdate).toHaveBeenCalledWith({
      content: [],
      details: {
        mode: "single",
        results: [
          expect.objectContaining({
            agent: "Explore",
            description: "Finding auth code",
            state: "running",
            messages: [],
          }),
        ],
      },
    });
    expect(result.isError).toBeUndefined();
    expect(result.content[0].text).toBe("done");
    expect(result.details.results[0]).toMatchObject({
      messages: [],
      description: "Finding auth code",
      resultText: "done",
    });
  });

  it("preserves each subagent tool call in order", async () => {
    const toolCalls = [
      createPiToolCallRecord(
        { id: "call-read-1", name: "read", arguments: {} },
        "completed",
      ),
      createPiToolCallRecord(
        { id: "call-bash", name: "bash", arguments: {} },
        "completed",
      ),
      createPiToolCallRecord(
        { id: "call-read-2", name: "read", arguments: {} },
        "completed",
      ),
    ];
    runAgentMock.mockResolvedValue(successResult({ toolCalls }));
    const execute = await getExecute();
    const result = (await execute(
      "id",
      {
        agent: "Explore",
        task: "Inspect the project files",
        description: "Inspecting project files",
      },
      undefined,
      undefined,
      fakeCtx,
    )) as { details: { results: SingleRunResult[] } };

    expect(result.details.results[0].toolCalls).toEqual(toolCalls);
  });

  it("reports failure when runAgent returns a failed result", async () => {
    runAgentMock.mockResolvedValue(
      successResult({
        state: "failed",
        stopReason: "error",
        errorMessage: "boom",
      }),
    );
    const execute = await getExecute();
    const result = (await execute(
      "id",
      { agent: "Explore", task: "x" },
      undefined,
      undefined,
      fakeCtx,
    )) as {
      isError?: boolean;
      content: Array<{ text: string }>;
    };
    expect(result.isError).toBe(true);
    expect(result.content[0].text).toMatch(/boom/);
  });

  it("validates project-agent calls before requesting approval", async () => {
    const cwd = mkdtempSync(join(tmpdir(), "posthog-subagent-validation-"));
    try {
      const agentsDirectory = join(cwd, ".pi", "agents");
      mkdirSync(agentsDirectory, { recursive: true });
      writeFileSync(
        join(agentsDirectory, "Worker.md"),
        `---\nname: Worker\ndescription: Test worker\ntools: read\n---\n`,
      );
      const confirm = vi.fn(async () => true);
      const execute = await getExecute();
      const result = (await execute(
        "id",
        {
          agentScope: "both",
          tasks: Array.from({ length: 5 }, () => ({
            agent: "Worker",
            task: "work",
          })),
        },
        undefined,
        undefined,
        { ...fakeCtx, cwd, ui: { ...fakeCtx.ui, confirm } },
      )) as { isError?: boolean; content: Array<{ text: string }> };

      expect(result.isError).toBe(true);
      expect(result.content[0].text).toMatch(/Too many parallel tasks/);
      expect(confirm).not.toHaveBeenCalled();
    } finally {
      rmSync(cwd, { recursive: true, force: true });
    }
  });

  it("dispatches parallel tasks concurrently", async () => {
    const tasks = [
      { agent: "Explore", task: "a" },
      { agent: "Plan", task: "b" },
    ];
    const pendingResults: Array<() => void> = [];
    runAgentMock.mockImplementation(
      ({ task }: { task: string }) =>
        new Promise<SingleRunResult>((resolve) => {
          pendingResults.push(() => resolve(successResult({ task })));
        }),
    );

    const execute = await getExecute();
    const resultPromise = execute(
      "id",
      { tasks },
      undefined,
      undefined,
      fakeCtx,
    ) as Promise<{
      isError?: boolean;
      content: Array<{ text: string }>;
    }>;

    await vi.waitFor(() => expect(runAgentMock).toHaveBeenCalledTimes(2));
    for (const resolve of pendingResults) {
      resolve();
    }
    const result = await resultPromise;

    expect(result.isError).toBeUndefined();
    expect(result.content[0].text).toMatch(/Parallel: 2\/2 succeeded/);
  });

  it.each([
    {
      name: "all failed",
      failed: ["a", "b"],
      isError: true,
      summary: /0\/2 succeeded/,
    },
    {
      name: "partially failed",
      failed: ["a"],
      isError: undefined,
      summary: /1\/2 succeeded/,
    },
  ])(
    "flags a $name parallel batch (isError=$isError)",
    async ({ failed, isError, summary }) => {
      runAgentMock.mockImplementation(async ({ task }: { task: string }) =>
        failed.includes(task)
          ? successResult({
              task,
              state: "failed",
              stopReason: "error",
              errorMessage: "boom",
            })
          : successResult({ task }),
      );
      const execute = await getExecute();
      const result = (await execute(
        "id",
        {
          tasks: [
            { agent: "Explore", task: "a" },
            { agent: "Plan", task: "b" },
          ],
        },
        undefined,
        undefined,
        fakeCtx,
      )) as { isError?: boolean; content: Array<{ text: string }> };
      expect(result.isError).toBe(isError);
      expect(result.content[0].text).toMatch(summary);
    },
  );
});
