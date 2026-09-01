import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";
import { beforeEach, describe, expect, it, vi } from "vitest";

const { runAgentMock, runPoolMock } = vi.hoisted(() => ({
  runAgentMock: vi.fn(),
  runPoolMock: vi.fn(),
}));

vi.mock("./run-agent", async () => {
  const actual =
    await vi.importActual<typeof import("./run-agent")>("./run-agent");
  return { ...actual, runAgent: runAgentMock };
});
vi.mock("./process/pool", () => ({ runPool: runPoolMock }));

import { createSubagentExtension } from "./extension";
import type { SingleRunResult } from "./run-agent";

function successResult(
  overrides: Partial<SingleRunResult> = {},
): SingleRunResult {
  return {
    runId: "test-run-id",
    startedAt: Date.now(),
    agent: "Explore",
    task: "look around",
    exitCode: 0,
    messages: [
      { role: "assistant", content: [{ type: "text", text: "done" }] } as never,
    ],
    stderr: "",
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
  createSubagentExtension()(pi);
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
    runPoolMock.mockReset();
  });

  it("errors when neither single nor parallel params are provided", async () => {
    const execute = await getExecute();
    const result = (await execute("id", {}, undefined, undefined, fakeCtx)) as {
      isError?: boolean;
      content: Array<{ text: string }>;
    };
    expect(result.isError).toBe(true);
    expect(result.content[0].text).toMatch(/Provide exactly one of/);
    expect(runAgentMock).not.toHaveBeenCalled();
  });

  it("errors when both single and parallel params are provided", async () => {
    const execute = await getExecute();
    const result = (await execute(
      "id",
      { agent: "Explore", task: "x", tasks: [{ agent: "Explore", task: "y" }] },
      undefined,
      undefined,
      fakeCtx,
    )) as { isError?: boolean };
    expect(result.isError).toBe(true);
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
    const tasks = Array.from({ length: 9 }, () => ({
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
    expect(runPoolMock).not.toHaveBeenCalled();
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
    expect(runPoolMock).not.toHaveBeenCalled();
  });

  it("dispatches single mode to runAgent and reports success", async () => {
    runAgentMock.mockResolvedValue(successResult());
    const execute = await getExecute();
    const result = (await execute(
      "id",
      { agent: "Explore", task: "find auth code" },
      undefined,
      undefined,
      fakeCtx,
    )) as {
      isError?: boolean;
      content: Array<{ text: string }>;
    };
    expect(runAgentMock).toHaveBeenCalledTimes(1);
    expect(result.isError).toBeUndefined();
    expect(result.content[0].text).toBe("done");
  });

  it("reports failure when runAgent returns a failed result", async () => {
    runAgentMock.mockResolvedValue(
      successResult({ exitCode: 1, stopReason: "error", errorMessage: "boom" }),
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

  it("dispatches parallel mode through runPool", async () => {
    const tasks = [
      { agent: "Explore", task: "a" },
      { agent: "Plan", task: "b" },
    ];
    runPoolMock.mockImplementation(
      async (
        items: typeof tasks,
        _opts: unknown,
        fn: (item: unknown, i: number, s: AbortSignal) => unknown,
      ) => {
        return Promise.all(
          items.map((item, i) => fn(item, i, new AbortController().signal)),
        );
      },
    );
    runAgentMock.mockImplementation(async ({ task }: { task: string }) =>
      successResult({ task }),
    );

    const execute = await getExecute();
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

    expect(runPoolMock).toHaveBeenCalledTimes(1);
    expect(runAgentMock).toHaveBeenCalledTimes(2);
    expect(result.isError).toBeUndefined();
    expect(result.content[0].text).toMatch(/Parallel: 2\/2 succeeded/);
  });
});
