import type { AgentFlowRole } from "@posthog/shared";
import { AGENT_FLOW_ROLE_META } from "./roleMeta";

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

export function FlowRoleDots({ roles }: { roles: AgentFlowRole[] }) {
  return (
    <span className="flex shrink-0 items-center gap-1">
      {roles.map((role, roleIndex) => (
        <span
          // biome-ignore lint/suspicious/noArrayIndexKey: presets may repeat a role; order is static
          key={`${role}-${roleIndex}`}
          className={`size-1.5 rounded-full ${AGENT_FLOW_ROLE_META[role].dotClass}`}
        />
      ))}
    </span>
  );
}
