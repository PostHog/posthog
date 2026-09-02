import type { ContentBlock } from "@agentclientprotocol/sdk";
import { resolveService } from "@posthog/di/container";
import { toast } from "@posthog/ui/primitives/toast";
import { useReviewNavigationStore } from "../code-review/reviewNavigationStore";
import { DEFAULT_TAB_IDS } from "../panels/panelConstants";
import { usePanelLayoutStore } from "../panels/panelLayoutStore";
import { findTabInTree } from "../panels/panelTree";
import {
  AGENT_PROMPT_SENDER,
  type AgentPromptSender,
} from "./agentPromptSender";

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

  const { getReviewMode, setReviewMode } = useReviewNavigationStore.getState();
  if (getReviewMode(taskId) === "expanded") {
    setReviewMode(taskId, "split");
  }

  const { taskLayouts, setActiveTab } = usePanelLayoutStore.getState();
  const layout = taskLayouts[taskId];
  if (layout) {
    const result = findTabInTree(layout.panelTree, DEFAULT_TAB_IDS.LOGS);
    if (result) {
      setActiveTab(taskId, result.panelId, DEFAULT_TAB_IDS.LOGS);
    }
  }

  return sendPromise;
}
