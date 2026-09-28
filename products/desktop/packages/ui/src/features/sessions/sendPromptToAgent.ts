import type { ContentBlock } from "@agentclientprotocol/sdk";
import { resolveService } from "@posthog/di/container";
import { toast } from "@posthog/ui/primitives/toast";
import {
  AGENT_PROMPT_SENDER,
  type AgentPromptSender,
} from "./agentPromptSender";
import { showTaskChat } from "./showTaskChat";

/**
 * Sends a prompt to the agent session for a task, collapses the review
 * panel to split mode if expanded, and switches to the logs/chat tab.
 */
export function sendPromptToAgent(
  taskId: string,
  prompt: string | ContentBlock[],
): Promise<boolean> {
  const sendPromise = resolveService<AgentPromptSender>(AGENT_PROMPT_SENDER)(
    taskId,
    prompt,
  )
    .then(() => true)
    .catch((error: unknown) => {
      toast.error(
        error instanceof Error
          ? error.message
          : "Failed to send your message to the agent. Please try again.",
      );
      return false;
    });

  showTaskChat(taskId);

  return sendPromise;
}
