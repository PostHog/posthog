import { RUNTIMES, type Runtime } from "./model-catalog";

/**
 * The harnesses a task may run on. Generated from the task model catalog, which the backend
 * validates a run against, so this list and the API cannot disagree.
 */
export const AGENT_RUNTIMES = RUNTIMES;

export type AgentRuntime = Runtime;
