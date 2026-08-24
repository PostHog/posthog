import type { ContentBlock } from "@agentclientprotocol/sdk";

export type AgentPromptSender = (
  taskId: string,
  prompt: string | ContentBlock[],
) => Promise<void>;

export const AGENT_PROMPT_SENDER = Symbol.for("posthog.ui.AgentPromptSender");
