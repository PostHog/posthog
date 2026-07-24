export const AGENT_RUNTIMES = ["acp", "pi"] as const;

export type AgentRuntime = (typeof AGENT_RUNTIMES)[number];
