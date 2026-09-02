import type { FixWithAgentPrompt } from "@posthog/core/git-interaction/errorPrompts";
import { useAppView } from "@posthog/ui/router/useAppView";
import { useCallback } from "react";
import { sendPromptToAgent } from "../sessions/sendPromptToAgent";
import { useSessionSelector } from "../sessions/useSession";

/**
 * Hook that sends a structured error prompt to the active agent session.
 * Derives taskId and session readiness from stores.
 *
 * `canFixWithAgent` is true when there's an active, connected session.
 */
export function useFixWithAgent(
  buildPrompt: (error: string) => FixWithAgentPrompt,
): {
  canFixWithAgent: boolean;
  fixWithAgent: (error: string) => Promise<void>;
} {
  const view = useAppView();
  const taskId = view.type === "task-detail" ? view.taskId : undefined;
  // Only the readiness flag is needed here — reading it as a primitive avoids
  // re-rendering every consumer (diff views) on each streamed token.
  const isSessionReady = useSessionSelector(
    taskId,
    (s) => s?.status === "connected",
  );

  const canFixWithAgent = !!(taskId && isSessionReady);

  const fixWithAgent = useCallback(
    async (error: string) => {
      if (!taskId || !isSessionReady) return;

      const { label, context } = buildPrompt(error);

      const prompt = `<error_context label="${label}">${context}</error_context>\n\n\`\`\`\n${error}\n\`\`\``;
      sendPromptToAgent(taskId, prompt);
    },
    [buildPrompt, taskId, isSessionReady],
  );

  return { canFixWithAgent, fixWithAgent };
}
