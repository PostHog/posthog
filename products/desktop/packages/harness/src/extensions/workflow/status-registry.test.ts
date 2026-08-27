import { afterEach, describe, expect, it, vi } from "vitest";
import {
  __resetWorkflowsForTesting,
  getWorkflow,
  listWorkflows,
  removeWorkflow,
  subscribeToWorkflows,
  upsertWorkflow,
} from "./status-registry";

afterEach(__resetWorkflowsForTesting);

const snapshot = {
  workflowId: "call-1",
  startedAt: 1,
  phases: ["Scan"],
  agents: [],
  logs: [],
  tokensSpent: 0,
};

describe("workflow status registry", () => {
  it("publishes active workflow updates and removes completed workflows", () => {
    const listener = vi.fn();
    const unsubscribe = subscribeToWorkflows(listener);
    upsertWorkflow(snapshot);
    expect(getWorkflow("call-1")).toEqual(snapshot);
    expect(listWorkflows()).toEqual([snapshot]);
    removeWorkflow("call-1");
    expect(listWorkflows()).toEqual([]);
    expect(listener).toHaveBeenCalledTimes(2);
    unsubscribe();
  });
});
