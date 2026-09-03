export const AGENT_RUNTIMES = ["acp", "pi"] as const;

export type AgentRuntime = (typeof AGENT_RUNTIMES)[number];

/** Fleet-wide harness when a user has no explicit choice saved. Remote-configured via DEFAULT_HARNESS_FLAG. */
export const DEFAULT_AGENT_RUNTIME: AgentRuntime = "pi";

export function isAgentRuntime(value: unknown): value is AgentRuntime {
  return (AGENT_RUNTIMES as readonly string[]).includes(value as string);
}
