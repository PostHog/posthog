import type { Schemas } from "@posthog/api-client";
import {
  canApplyTitleFromPrompts,
  decideTitleGeneration,
  formatPromptsForTitleInput,
  isAutoTitleLocked,
  selectPromptsForTitle,
} from "@posthog/core/sessions/chatTitle";
import { extractUserPromptsFromEvents } from "@posthog/core/sessions/sessionEvents";
import type { SessionService } from "@posthog/core/sessions/sessionService";
import { SESSION_SERVICE } from "@posthog/core/sessions/sessionService";
import { TITLE_GENERATOR_SERVICE } from "@posthog/core/sessions/titleGeneratorIdentifiers";
import type { TitleGeneratorService } from "@posthog/core/sessions/titleGeneratorService";
import { useService } from "@posthog/di/react";
import type { Task } from "@posthog/shared/domain-types";
import { useOptionalAuthenticatedClient } from "@posthog/ui/features/auth/authClient";
import { useAuthStateValue } from "@posthog/ui/features/auth/store";
import {
  sessionStoreSetters,
  useSessionStore,
} from "@posthog/ui/features/sessions/sessionStore";
import {
  type TitleGenerationEntry,
  titleGenerationStoreApi,
} from "@posthog/ui/features/sessions/titleGenerationStore";
import { taskKeys } from "@posthog/ui/features/tasks/taskKeys";
import { logger } from "@posthog/ui/shell/logger";
import { titleAttachmentStoreApi } from "@posthog/ui/shell/titleAttachmentStore";
import { type QueryClient, useQueryClient } from "@tanstack/react-query";
import { useEffect } from "react";

const log = logger.scope("chat-title-generator");

function getCachedTask(
  queryClient: QueryClient,
  taskId: string,
): Task | undefined {
  return queryClient
    .getQueriesData<Task[]>({ queryKey: taskKeys.lists() })
    .flatMap(([, tasks]) => tasks ?? [])
    .find((t) => t.id === taskId);
}

export function useChatTitleGenerator(task: Task): void {
  const taskId = task.id;
  const sessionService = useService<SessionService>(SESSION_SERVICE);
  const titleGenerator = useService<TitleGeneratorService>(
    TITLE_GENERATOR_SERVICE,
  );
  const queryClient = useQueryClient();
  const client = useOptionalAuthenticatedClient();
  const isAuthenticated = useAuthStateValue(
    (state) => state.status === "authenticated" && !!state.cloudRegion,
  );

  const promptCount = useSessionStore((state) => {
    const taskRunId = state.taskIdIndex[taskId];
    if (!taskRunId) return 0;
    const session = state.sessions[taskRunId];
    if (!session?.events) return 0;
    return extractUserPromptsFromEvents(session.events).length;
  });

  useEffect(() => {
    if (!isAuthenticated) return;

    const bookkeeping = titleGenerationStoreApi.get(taskId);
    if (bookkeeping.inFlight) return;

    const state = useSessionStore.getState();
    const taskRunId = state.taskIdIndex[taskId];
    const session = taskRunId ? state.sessions[taskRunId] : undefined;
    const isTitleLocked = () =>
      isAutoTitleLocked(getCachedTask(queryClient, taskId) ?? task);

    const { shouldGenerateFromPrompts, shouldGenerateFromTaskDescription } =
      decideTitleGeneration({
        promptCount,
        lastGeneratedAtCount: bookkeeping.lastGeneratedAtCount,
        initialDescriptionHandled: bookkeeping.initialDescriptionHandled,
        task,
        isTitleLocked,
        hasSummary: !!session?.conversationSummary,
      });

    if (!shouldGenerateFromPrompts && !shouldGenerateFromTaskDescription) {
      return;
    }

    titleGenerationStoreApi.update(taskId, { inFlight: true });

    let rawContent = task.description;

    if (shouldGenerateFromPrompts) {
      if (!session?.events) {
        titleGenerationStoreApi.update(taskId, { inFlight: false });
        return;
      }

      const allPrompts = extractUserPromptsFromEvents(session.events);
      const promptsForTitle = selectPromptsForTitle(allPrompts, promptCount);

      rawContent = formatPromptsForTitleInput(promptsForTitle);
    }

    const run = async () => {
      try {
        const attachmentPaths = titleAttachmentStoreApi.get(taskId) ?? [];
        const content = await titleGenerator.enrichDescriptionWithFileContent(
          rawContent,
          attachmentPaths,
        );
        const result = await titleGenerator.generateTitleAndSummary(content);
        if (result) {
          // Drop the stash once a title has been successfully produced so the
          // map doesn't grow across a long-lived session. Keeping it on failure
          // lets the prompt-based regeneration at REGENERATE_INTERVAL pick it
          // up and try again with the file contents.
          titleAttachmentStoreApi.clear(taskId);
          const { title, summary } = result;

          if (title && isTitleLocked()) {
            log.debug("Skipping auto-title, user renamed task", { taskId });
          } else if (
            title &&
            !canApplyTitleFromPrompts(
              promptCount,
              getCachedTask(queryClient, taskId) ?? task,
            )
          ) {
            log.debug("Skipping auto-title, keeping original-context title", {
              taskId,
              promptCount,
            });
          } else if (title) {
            if (client) {
              await client.updateTask(taskId, { title });
              queryClient.setQueriesData<Task[]>(
                { queryKey: taskKeys.lists() },
                (old) =>
                  old?.map((task) =>
                    task.id === taskId ? { ...task, title } : task,
                  ),
              );
              queryClient.setQueriesData<Schemas.TaskSummary[]>(
                { queryKey: taskKeys.allSummaries() },
                (old) =>
                  old?.map((task) =>
                    task.id === taskId ? { ...task, title } : task,
                  ),
              );
              queryClient.setQueryData<Task>(taskKeys.detail(taskId), (old) =>
                old ? { ...old, title } : old,
              );
              sessionService.updateSessionTaskTitle(taskId, title);
              log.debug("Updated task title from conversation", {
                taskId,
                promptCount,
              });
            }
          }

          if (summary && taskRunId) {
            sessionStoreSetters.updateSession(taskRunId, {
              conversationSummary: result.summary,
            });

            log.debug("Updated task summary from conversation", {
              taskId,
              promptCount,
            });
          }
        }
      } catch (error) {
        log.error("Failed to update task title", { taskId, error });
      } finally {
        const patch: Partial<TitleGenerationEntry> = { inFlight: false };
        if (shouldGenerateFromPrompts) {
          patch.lastGeneratedAtCount = promptCount;
        }
        if (shouldGenerateFromTaskDescription) {
          patch.initialDescriptionHandled = true;
        }
        titleGenerationStoreApi.update(taskId, patch);
      }
    };

    run();
  }, [
    isAuthenticated,
    promptCount,
    taskId,
    task,
    client,
    queryClient,
    sessionService,
    titleGenerator,
  ]);
}
