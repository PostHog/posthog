import { extractUserPromptsFromEvents } from "@posthog/core/sessions/sessionEvents";
import { TITLE_GENERATOR_SERVICE } from "@posthog/core/sessions/titleGeneratorIdentifiers";
import type { TitleGeneratorService } from "@posthog/core/sessions/titleGeneratorService";
import { useService } from "@posthog/di/react";
import { useAuthStateValue } from "@posthog/ui/features/auth/store";
import type { SessionState } from "@posthog/ui/features/sessions/sessionStore";
import { useSessionStore } from "@posthog/ui/features/sessions/sessionStore";
import {
  type TurnStatusEntry,
  turnStatusStoreApi,
} from "@posthog/ui/features/sessions/turnStatusStore";
import { useEffect } from "react";
import { shallow } from "zustand/shallow";

interface ActivePrompt {
  requestKey: string | null;
  text: string | null;
}

const INACTIVE_PROMPT: ActivePrompt = {
  requestKey: null,
  text: null,
};

function selectActivePrompt(state: SessionState, taskId: string): ActivePrompt {
  const taskRunId = state.taskIdIndex[taskId];
  const session = taskRunId ? state.sessions[taskRunId] : undefined;
  if (!session?.isPromptPending) return INACTIVE_PROMPT;

  const prompts = extractUserPromptsFromEvents(session.events);
  const text = prompts.at(-1) ?? null;
  if (!text) return INACTIVE_PROMPT;

  return {
    requestKey: `${taskRunId}:${prompts.length}`,
    text,
  };
}

export function useTurnStatusGenerator(taskId: string): void {
  const titleGenerator = useService<TitleGeneratorService>(
    TITLE_GENERATOR_SERVICE,
  );
  const isAuthenticated = useAuthStateValue(
    (state) => state.status === "authenticated" && !!state.cloudRegion,
  );
  const activePrompt = useSessionStore(
    (state) => selectActivePrompt(state, taskId),
    shallow,
  );

  useEffect(() => {
    const { requestKey, text } = activePrompt;
    if (!requestKey || !text) {
      if (turnStatusStoreApi.get(taskId).text !== null) {
        turnStatusStoreApi.update(taskId, { text: null });
      }
      return;
    }
    if (!isAuthenticated) return;

    const existing = turnStatusStoreApi.get(taskId);
    if (existing.requestKey === requestKey) return;

    turnStatusStoreApi.update(taskId, { requestKey, text: null });

    void titleGenerator.generateTurnStatus(text).then((status) => {
      if (!status) return;

      const currentPrompt = selectActivePrompt(
        useSessionStore.getState(),
        taskId,
      );
      const currentStatus: TurnStatusEntry = turnStatusStoreApi.get(taskId);
      if (
        currentPrompt.requestKey === requestKey &&
        currentStatus.requestKey === requestKey
      ) {
        turnStatusStoreApi.update(taskId, { text: status });
      }
    });
  }, [activePrompt, isAuthenticated, taskId, titleGenerator]);
}
