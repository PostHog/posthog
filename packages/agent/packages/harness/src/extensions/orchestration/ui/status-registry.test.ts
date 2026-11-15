import { afterEach, describe, expect, it, vi } from "vitest";
import {
  __resetOrchestrationForTesting,
  type AgentRunSnapshot,
  focusFromEditor,
  getWorkflow,
  isFocused,
  listWorkflows,
  removeAgentRun,
  removeWorkflow,
  subscribeToOrchestration,
  upsertAgentRun,
  upsertWorkflow,
} from "./status-registry";

afterEach(__resetOrchestrationForTesting);

const snapshot = {
  workflowId: "call-1",
  startedAt: 1,
  phases: ["Scan"],
  agents: [],
  logs: [],
  tokensSpent: 0,
};

const agentSnapshot = (runId: string): AgentRunSnapshot => ({
  runId,
  agent: "scout",
  task: "find it",
  startedAt: 1,
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
});

describe("workflow status registry", () => {
  it("publishes active workflow updates and removes completed workflows", () => {
    const listener = vi.fn();
    const unsubscribe = subscribeToOrchestration(listener);
    upsertWorkflow(snapshot);
    expect(getWorkflow("call-1")).toEqual(snapshot);
    expect(listWorkflows()).toEqual([snapshot]);
    removeWorkflow("call-1");
    expect(listWorkflows()).toEqual([]);
    expect(listener).toHaveBeenCalledTimes(2);
    unsubscribe();
  });
});

describe("agent run focus", () => {
  it.each([
    { runs: 1, stillFocused: false },
    { runs: 2, stillFocused: true },
  ])(
    "clears footer focus only when the last focused agent run ends ($runs run(s))",
    ({ runs, stillFocused }) => {
      for (let i = 0; i < runs; i++) {
        upsertAgentRun(agentSnapshot(`run-${i}`));
      }
      expect(focusFromEditor()).toBe(true);
      expect(isFocused()).toBe(true);

      removeAgentRun("run-0");
      expect(isFocused()).toBe(stillFocused);
    },
  );
});
