import { describe, expect, it } from "vitest";
import {
  type AgentFlowDefinition,
  agentFlowSkillSlug,
  buildAgentFlowSkillBody,
  parseAgentFlowSkillFile,
  serializeAgentFlowSkillFile,
} from "./agent-flow";

const flow: AgentFlowDefinition = {
  id: "flow-1",
  name: "Plan and build",
  steps: [
    {
      id: "s1",
      name: "Plan",
      role: "planner",
      model: { provider: "posthog", id: "m1", name: "Model One" },
      effort: "high",
      approvalAfter: true,
      instructions: "Keep the plan short.",
    },
    {
      id: "s2",
      name: "Build",
      role: "executor",
      model: { provider: "posthog", id: "m2", name: "Model Two" },
      effort: "medium",
      approvalAfter: false,
    },
  ],
};

describe("agent flow skill files", () => {
  it("round-trips a flow through the skill file", () => {
    expect(parseAgentFlowSkillFile(serializeAgentFlowSkillFile(flow))).toEqual(
      flow,
    );
  });

  it.each([
    ["not json", "{nope"],
    ["missing steps", JSON.stringify({ id: "x", name: "y" })],
    ["one step", JSON.stringify({ ...flow, steps: flow.steps.slice(0, 1) })],
  ])("returns null for %s", (_label, content) => {
    expect(parseAgentFlowSkillFile(content)).toBeNull();
  });

  it.each([
    ["Plan and build", "plan-and-build"],
    ["  Weird -- Name!! ", "weird-name"],
    ["///", "flow"],
    ["A".repeat(80), "a".repeat(64)],
  ])("slugs %j to %j", (name, expected) => {
    expect(agentFlowSkillSlug(name)).toBe(expected);
  });

  it("describes every step and approval gate in the skill body", () => {
    const body = buildAgentFlowSkillBody(flow);
    expect(body).toContain("**Plan** (planner)");
    expect(body).toContain("**Build** (executor)");
    expect(body).toContain("wait for the user to approve");
    expect(body).toContain("flow.json");
    expect(body).toContain("run_agent_flow` tool is available, call it now");
    expect(body).toContain('name: "plan-and-build"');
  });
});
