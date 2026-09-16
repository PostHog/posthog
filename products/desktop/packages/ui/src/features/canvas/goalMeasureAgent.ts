import type { Adapter, AgentRuntime } from "@posthog/shared";
import type { EffortLevel } from "@posthog/shared/domain-types";

export interface AgentChoice {
  adapter: Adapter;
  model: string;
  reasoningLevel: EffortLevel;
  runtime: AgentRuntime;
}

export const GOAL_MEASURE_AGENT: AgentChoice = {
  adapter: "codex",
  model: "gpt-5.6-luna",
  reasoningLevel: "high",
  runtime: "pi",
};
