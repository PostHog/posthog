import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";
import { beforeEach, describe, expect, it, vi } from "vitest";

const { runAgentMock } = vi.hoisted(() => ({ runAgentMock: vi.fn() }));

vi.mock("../subagent/run-agent", async () => {
  const actual = await vi.importActual<typeof import("../subagent/run-agent")>(
    "../subagent/run-agent",
  );
  return { ...actual, runAgent: runAgentMock };
});

import type { SingleRunResult } from "../subagent/run-agent";
import { createWorkflowExtension } from "./extension";

function successResult(
  overrides: Partial<SingleRunResult> = {},
): SingleRunResult {
  return {
    runId: "test-run-id",
    startedAt: Date.now(),
    agent: "Explore",
    task: "task",
    exitCode: 0,
    messages: [
      {
        role: "assistant",
        content: [{ type: "text", text: "agent output" }],
      } as never,
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
  createWorkflowExtension()(pi);
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

  it("does not stream runtime state into the tool result", async () => {
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
    expect(onUpdate).not.toHaveBeenCalled();
    expect(runAgentMock).toHaveBeenCalledWith(
      expect.objectContaining({
        publishStatus: false,
        onUpdate: expect.any(Function),
      }),
    );
  });

  it.each([
    ["strong", "claude-opus-4-8"],
    ["medium", "claude-sonnet-5"],
    ["cheap", "claude-haiku-4-5"],
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
    expect(passedAgent.model).toBe("claude-haiku-4-5"); // Explore's own bundled default
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
