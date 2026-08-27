import type { AgentFlowRole } from "@posthog/shared";

export const FLOW_PRESETS: Array<{
  name: string;
  description: string;
  roles: AgentFlowRole[];
}> = [
  {
    name: "Planner and executor",
    description: "Create a plan, approve it, and then implement it.",
    roles: ["planner", "executor"],
  },
  {
    name: "Research, plan, and execute",
    description: "Research the code, make a plan, and then implement it.",
    roles: ["researcher", "planner", "executor"],
  },
  {
    name: "Plan, execute, and review",
    description: "Make a plan, implement it, and review the result.",
    roles: ["planner", "executor", "reviewer"],
  },
];
