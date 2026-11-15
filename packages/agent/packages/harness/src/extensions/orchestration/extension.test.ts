import type { ExtensionContext } from "@earendil-works/pi-coding-agent";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { createOrchestrationExtension } from "./extension";
import {
  __resetOrchestrationForTesting,
  type AgentRunSnapshot,
  removeAgentRun,
  upsertAgentRun,
} from "./ui/status-registry";

type Handler = (event: unknown, context: ExtensionContext) => void;

function fakePi(): {
  pi: { on: (event: string, handler: Handler) => void; registerTool: unknown };
  emit: (event: string, context: ExtensionContext) => void;
} {
  const handlers = new Map<string, Handler[]>();
  const pi = {
    on: (event: string, handler: Handler) => {
      handlers.set(event, [...(handlers.get(event) ?? []), handler]);
    },
    registerTool: vi.fn(),
  };

  return {
    pi,
    emit: (event: string, context: ExtensionContext) => {
      for (const handler of handlers.get(event) ?? []) {
        handler({}, context);
      }
    },
  };
}

function fakeContext(): {
  context: ExtensionContext;
  setFooter: ReturnType<typeof vi.fn>;
} {
  const setFooter = vi.fn();
  const context = {
    ui: {
      setEditorComponent: vi.fn(),
      setFooter,
    },
  } as unknown as ExtensionContext;
  return { context, setFooter };
}

function activeRun(runId: string): AgentRunSnapshot {
  return {
    runId,
    agent: "Explore",
    task: "Inspect the repository",
    startedAt: Date.now(),
    usage: {
      input: 0,
      output: 0,
      cacheRead: 0,
      cacheWrite: 0,
      cost: 0,
      contextTokens: 0,
      turns: 0,
    },
    messages: [],
  };
}

describe("createOrchestrationExtension", () => {
  beforeEach(() => {
    __resetOrchestrationForTesting();
  });

  afterEach(() => {
    __resetOrchestrationForTesting();
  });

  it("restores status updates after a session restart", () => {
    const { pi, emit } = fakePi();
    createOrchestrationExtension()(pi as never);

    const first = fakeContext();
    emit("session_start", first.context);
    upsertAgentRun(activeRun("first-run"));
    expect(first.setFooter).toHaveBeenCalledWith(expect.any(Function));

    removeAgentRun("first-run");
    emit("session_shutdown", first.context);

    const second = fakeContext();
    emit("session_start", second.context);
    upsertAgentRun(activeRun("second-run"));
    expect(second.setFooter).toHaveBeenCalledWith(expect.any(Function));

    removeAgentRun("second-run");
    emit("session_shutdown", second.context);
  });
});
