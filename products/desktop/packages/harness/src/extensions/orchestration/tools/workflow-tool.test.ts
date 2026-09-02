import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";
import { beforeEach, describe, expect, it, vi } from "vitest";

const { runAgentMock } = vi.hoisted(() => ({ runAgentMock: vi.fn() }));

vi.mock("../run-agent", async () => {
  const actual =
    await vi.importActual<typeof import("../run-agent")>("../run-agent");
  return { ...actual, runAgent: runAgentMock };
});

import type { SingleRunResult } from "../run-agent";
import { registerWorkflowTool } from "./workflow-tool";

function successResult(
  overrides: Partial<SingleRunResult> = {},
): SingleRunResult {
  return {
    runId: "test-run-id",
    startedAt: Date.now(),
    agent: "Explore",
    task: "task",
    state: "completed",
    messages: [
      {
        role: "assistant",
        content: [{ type: "text", text: "agent output" }],
      } as never,
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
    | { name: string; execute: (...args: unknown[]) => Promise<unknown> }
    | undefined;
  const pi = {
    registerTool: (tool: {
      name: string;
      execute: (...args: unknown[]) => Promise<unknown>;
    }) => {
      registered = tool;
    },
    registerCommand: () => {},
    on: () => {},
    events: { on: () => {}, emit: () => {} },
  } as unknown as ExtensionAPI;
  registerWorkflowTool(pi);
  if (!registered || registered.name !== "workflow")
    throw new Error("workflow tool was not registered");
  return registered.execute;
}

const fakeCtx = {
  cwd: "/repo",
  hasUI: true,
  isProjectTrusted: () => true,
  ui: { confirm: async () => true },
};

type ToolResult = {
  isError?: boolean;
  content: Array<{ text: string }>;
  details: { agents: Array<{ status: string }>; phases: string[] };
};

describe("workflow tool", () => {
  beforeEach(() => {
    runAgentMock.mockReset();
  });

  it("runs a script whose agent() calls go through runAgent", async () => {
    runAgentMock.mockResolvedValue(successResult());
    const execute = await getExecute();
    const result = (await execute(
      "id",
      {
        script: `export const meta = { name: 'smoke', description: 'd' }
phase('Scan')
const out = await agent('look around', { label: 'recon' })
return { out }`,
      },
      undefined,
      undefined,
      fakeCtx,
    )) as ToolResult;

    expect(result.isError).toBeUndefined();
    expect(result.content[0].text).toContain('"out": "agent output"');
    expect(result.details.phases).toEqual(["Scan"]);
    expect(result.details.agents).toEqual([
      expect.objectContaining({ label: "recon", status: "done" }),
    ]);
    expect(runAgentMock).toHaveBeenCalledWith(
      expect.objectContaining({ task: "look around", ctx: fakeCtx }),
    );
  });

  it("parses schema'd agent output and accounts real tokens", async () => {
    runAgentMock.mockResolvedValue(
      successResult({
        messages: [
          {
            role: "assistant",
            content: [{ type: "text", text: '{"files": ["a.ts", "b.ts"]}' }],
            usage: { input: 300, output: 100 },
          } as never,
        ],
        usage: {
          input: 300,
          output: 100,
          cacheRead: 0,
          cacheWrite: 0,
          cost: 0,
          contextTokens: 400,
          turns: 1,
        },
      }),
    );
    const execute = await getExecute();
    const result = (await execute(
      "id",
      {
        script: `const inv = await agent('list', { label: 'inv', schema: { type: 'object', required: ['files'] } })
return { count: inv.files.length }`,
      },
      undefined,
      undefined,
      fakeCtx,
    )) as ToolResult & { details: { tokensSpent?: number } };

    expect(result.isError).toBeUndefined();
    expect(result.content[0].text).toContain('"count": 2');
    expect(result.details.tokensSpent).toBe(400);
    // The schema contract was appended to the child's task prompt.
    expect(runAgentMock).toHaveBeenCalledWith(
      expect.objectContaining({
        task: expect.stringContaining("Output contract"),
      }),
    );
  });

  it("streams structured workflow state while agents run", async () => {
    runAgentMock.mockResolvedValue(successResult());
    const execute = await getExecute();
    const onUpdate = vi.fn();
    await execute(
      "id",
      { script: "return await agent('x', { label: 'only' })" },
      undefined,
      onUpdate,
      fakeCtx,
    );
    expect(onUpdate).toHaveBeenCalledWith({
      content: [],
      details: expect.objectContaining({
        agents: [
          expect.objectContaining({
            label: "only",
            status: "running",
          }),
        ],
        done: false,
      }),
    });
    expect(runAgentMock).toHaveBeenCalledWith(
      expect.objectContaining({
        publishStatus: false,
        useAutoContext: false,
        onUpdate: expect.any(Function),
      }),
    );
  });

  it("publishes canceled agent state before an aborted workflow exits", async () => {
    const controller = new AbortController();
    runAgentMock.mockImplementation(
      ({
        signal,
        onUpdate,
      }: {
        signal: AbortSignal;
        onUpdate: (result: SingleRunResult) => void;
      }) => {
        const running = successResult({ state: "running" });
        onUpdate(running);
        return new Promise<SingleRunResult>((resolve) => {
          signal.addEventListener(
            "abort",
            () =>
              resolve(
                successResult({
                  state: "aborted",
                  stopReason: "aborted",
                  errorMessage: "Subagent was aborted",
                }),
              ),
            { once: true },
          );
        });
      },
    );
    const execute = await getExecute();
    const onUpdate = vi.fn();
    const execution = execute(
      "id",
      { script: "return await agent('slow', { label: 'worker' })" },
      controller.signal,
      onUpdate,
      fakeCtx,
    );

    await vi.waitFor(() => expect(runAgentMock).toHaveBeenCalledOnce());
    controller.abort();

    const result = (await execution) as {
      content: Array<{ text: string }>;
      details: { cancelled?: boolean; done: boolean };
      isError?: boolean;
    };
    expect(result.content[0].text).toBe("Workflow was canceled");
    expect(result.details).toMatchObject({ done: true, cancelled: true });
    expect(result.isError).toBeUndefined();
    expect(onUpdate).toHaveBeenCalledWith({
      content: [],
      details: expect.objectContaining({
        done: true,
        agents: [expect.objectContaining({ status: "aborted" })],
      }),
    });
  });

  it.each([
    ["strong", "gpt-5.6-sol"],
    ["medium", "gpt-5.6-terra"],
    ["cheap", "gpt-5.6-luna"],
  ])(
    "resolves model tier %s to %s before calling runAgent",
    async (tier, expectedModel) => {
      runAgentMock.mockResolvedValue(successResult());
      const execute = await getExecute();
      await execute(
        "id",
        {
          script: `return await agent('x', { model: '${tier}' })`,
        },
        undefined,
        undefined,
        fakeCtx,
      );
      expect(runAgentMock).toHaveBeenCalledWith(
        expect.objectContaining({
          agent: expect.objectContaining({ model: expectedModel }),
        }),
      );
    },
  );

  it("passes a literal model id through unresolved (escape hatch)", async () => {
    runAgentMock.mockResolvedValue(successResult());
    const execute = await getExecute();
    await execute(
      "id",
      { script: `return await agent('x', { model: 'posthog/gpt-5.3-codex' })` },
      undefined,
      undefined,
      fakeCtx,
    );
    expect(runAgentMock).toHaveBeenCalledWith(
      expect.objectContaining({
        agent: expect.objectContaining({ model: "posthog/gpt-5.3-codex" }),
      }),
    );
  });

  it("omitting model leaves the persona's own default model untouched", async () => {
    runAgentMock.mockResolvedValue(successResult());
    const execute = await getExecute();
    await execute(
      "id",
      { script: `return await agent('x')` },
      undefined,
      undefined,
      fakeCtx,
    );
    const passedAgent = runAgentMock.mock.calls[0][0].agent;
    expect(passedAgent.model).toBe("gpt-5.6-sol");
  });

  it("can dispatch to the General (read-write) persona by name", async () => {
    runAgentMock.mockResolvedValue(successResult({ agent: "General" }));
    const execute = await getExecute();
    const result = (await execute(
      "id",
      {
        script: `return await agent('x', { agent: 'General', label: 'impl' })`,
      },
      undefined,
      undefined,
      fakeCtx,
    )) as ToolResult;
    expect(result.isError).toBeUndefined();
    expect(runAgentMock).toHaveBeenCalledWith(
      expect.objectContaining({
        agent: expect.objectContaining({ name: "General" }),
      }),
    );
  });

  it("errors when the script never calls agent()", async () => {
    const execute = await getExecute();
    const result = (await execute(
      "id",
      { script: "return { ok: true }" },
      undefined,
      undefined,
      fakeCtx,
    )) as ToolResult;
    expect(result.isError).toBe(true);
    expect(result.content[0].text).toContain("must call agent()");
  });

  it("surfaces script errors as tool errors, not throws", async () => {
    const execute = await getExecute();
    const result = (await execute(
      "id",
      { script: "syntax error here(" },
      undefined,
      undefined,
      fakeCtx,
    )) as ToolResult;
    expect(result.isError).toBe(true);
    expect(result.content[0].text).toContain("Workflow failed:");
  });
});
