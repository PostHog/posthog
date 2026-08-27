import {
  EyeIcon,
  type Icon,
  ListChecksIcon,
  MagnifyingGlassIcon,
  WrenchIcon,
} from "@phosphor-icons/react";
import type { AgentFlowEffort, AgentFlowRole } from "@posthog/shared";

export const AGENT_FLOW_EFFORT_LABELS: Record<AgentFlowEffort, string> = {
  off: "No thinking",
  minimal: "Minimal",
  low: "Low effort",
  medium: "Medium effort",
  high: "High effort",
  xhigh: "Extra high effort",
  max: "Max effort",
};

export interface AgentFlowRoleMeta {
  label: string;
  icon: Icon;
  chipClass: string;
  dotClass: string;
}

export const AGENT_FLOW_ROLE_META: Record<AgentFlowRole, AgentFlowRoleMeta> = {
  researcher: {
    label: "Research",
    icon: MagnifyingGlassIcon,
    chipClass: "bg-blue-3 text-blue-11",
    dotClass: "bg-blue-9",
  },
  planner: {
    label: "Plan",
    icon: ListChecksIcon,
    chipClass: "bg-violet-3 text-violet-11",
    dotClass: "bg-violet-9",
  },
  executor: {
    label: "Implement",
    icon: WrenchIcon,
    chipClass: "bg-green-3 text-green-11",
    dotClass: "bg-green-9",
  },
  reviewer: {
    label: "Review",
    icon: EyeIcon,
    chipClass: "bg-orange-3 text-orange-11",
    dotClass: "bg-orange-9",
  },
};
