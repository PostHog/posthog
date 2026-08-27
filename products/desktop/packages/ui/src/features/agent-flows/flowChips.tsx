import type { AgentFlowDefinition, AgentFlowRole } from "@posthog/shared";
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

export function FlowStepChain({ flow }: { flow: AgentFlowDefinition }) {
  return (
    <div className="flex min-w-0 flex-wrap items-center gap-y-1">
      {flow.steps.map((step, stepIndex) => (
        <div key={step.id} className="flex items-center">
          {stepIndex > 0 ? (
            <span className="h-px w-3 shrink-0 bg-gray-6" />
          ) : null}
          <span className="flex items-center gap-1.5 rounded-full border border-gray-5 bg-gray-1 px-2 py-0.5 text-[11px] text-gray-11">
            <span
              className={`size-1.5 rounded-full ${AGENT_FLOW_ROLE_META[step.role].dotClass}`}
            />
            {step.name}
            <span className="text-gray-9">{step.model.name}</span>
          </span>
        </div>
      ))}
    </div>
  );
}

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
