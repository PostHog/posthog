import {
  isContentEmpty,
  textToContent,
  xmlToContent,
} from "@posthog/core/message-editor/content";
import {
  combineQueuedCloudPrompts,
  promptToQueuedEditorContent,
} from "@posthog/core/sessions/cloudPrompt";
import {
  SESSION_SERVICE,
  type SessionService,
} from "@posthog/core/sessions/sessionService";
import { useService } from "@posthog/di/react";
import { useHostTRPCClient } from "@posthog/host-router/react";
import type { Task } from "@posthog/shared/domain-types";
import {
  resolveLocalSkillPrompt,
  rewriteLocalSkillCommandPrompt,
  tryExecuteCodeCommand,
} from "@posthog/ui/features/message-editor/commands";
import { useDraftStore } from "@posthog/ui/features/message-editor/draftStore";
import { useMessagingMode } from "@posthog/ui/features/sessions/hooks/useMessagingMode";
import {
  type AgentSession,
  sessionStoreSetters,
} from "@posthog/ui/features/sessions/sessionStore";
import { useTaskViewed } from "@posthog/ui/features/sidebar/useTaskViewed";
import {
  SHELL_CLIENT,
  type ShellClient,
} from "@posthog/ui/features/terminal/shellClient";
import { toast } from "@posthog/ui/primitives/toast";
import { getAppViewSnapshot } from "@posthog/ui/router/useAppView";
import { logger } from "@posthog/ui/shell/logger";
import { useCallback, useRef } from "react";

const log = logger.scope("session-callbacks");

interface UseSessionCallbacksOptions {
  taskId: string;
  task: Task;
  session: AgentSession | undefined;
  repoPath: string | null;
}

export function useSessionCallbacks({
  taskId,
  task,
  session,
  repoPath,
}: UseSessionCallbacksOptions) {
  const sessionService = useService<SessionService>(SESSION_SERVICE);
  const shellClient = useService<ShellClient>(SHELL_CLIENT);
  const hostClient = useHostTRPCClient();
  const { markActivity, markAsViewed } = useTaskViewed();
  const { requestFocus, setPendingContent } = useDraftStore((s) => s.actions);

  const sessionRef = useRef(session);
  sessionRef.current = session;

  const messagingMode = useMessagingMode(taskId);

  const handleSendPrompt = useCallback(
    async (text: string): Promise<boolean> => {
      const currentSession = sessionRef.current;
      const currentEvents = currentSession?.events ?? [];
      const handled = await tryExecuteCodeCommand(text, {
        taskId,
        repoPath,
        session: currentSession
          ? {
              taskRunId: currentSession.taskRunId,
              logUrl: currentSession.logUrl,
              events: currentEvents,
            }
          : null,
        taskRun: task.latest_run ?? null,
      });
      if (handled) return true;

      let promptText =
        rewriteLocalSkillCommandPrompt(
          text,
          useDraftStore.getState().commands[taskId] ?? [],
        ) ?? null;

      if (!promptText) {
        try {
          promptText = await resolveLocalSkillPrompt(text, () =>
            hostClient.skills.list.query(),
          );
        } catch (error) {
          log.warn("Failed to resolve local skill command", { error });
        }
      }

      // Editing a queued message in place: update it where it sits in the
      // queue rather than sending a new prompt. If the target already drained
      // or was discarded, fall through and send it as a fresh message.
      const editingId =
        sessionStoreSetters.getSessionByTaskId(taskId)?.editingQueuedId;
      if (editingId) {
        try {
          const updated = await sessionService.updateQueuedMessage(
            taskId,
            editingId,
            promptText ?? text,
          );
          if (updated) {
            markAsViewed(taskId);
            return true;
          }
          // Target no longer queued — drop the stale hold and send as new.
          sessionService.clearEditingQueuedMessage(taskId);
        } catch (error) {
          const message =
            error instanceof Error ? error.message : "Failed to update message";
          toast.error(message);
          log.error("Failed to update queued message", error);
          // Keep the edit hold: releasing it would let the original, unedited
          // message drain and send — the opposite of what the user intended by
          // editing. The message stays held and the composer restores the
          // edited text (unless the user already started typing) so they can
          // retry the save or cancel the edit explicitly.
          if (isContentEmpty(useDraftStore.getState().drafts[taskId] ?? null)) {
            setPendingContent(taskId, xmlToContent(promptText ?? text));
            requestFocus(taskId);
          }
          return false;
        }
      }

      try {
        markAsViewed(taskId);
        markActivity(taskId);
        await sessionService.sendPrompt(taskId, promptText ?? text, {
          steer: messagingMode === "steer",
        });

        const view = getAppViewSnapshot();
        const isViewingTask =
          view?.type === "task-detail" && view?.taskId === taskId;
        if (isViewingTask) {
          markAsViewed(taskId);
        }
        return true;
      } catch (error) {
        const message =
          error instanceof Error ? error.message : "Failed to send message";
        toast.error(message);
        log.error("Failed to send prompt", error);
        return false;
      }
    },
    [
      taskId,
      repoPath,
      markActivity,
      markAsViewed,
      task.latest_run,
      sessionService,
      hostClient,
      messagingMode,
      setPendingContent,
      requestFocus,
    ],
  );

  const handleCancelPrompt = useCallback(async () => {
    // Stopping while a queued message is being edited: halt the turn but leave
    // the queue and the composer alone, since recalling the queue into the
    // composer would clobber the in-progress edit. The edit hold keeps the
    // queue from auto-sending until the edit is saved or cancelled.
    const currentSession = sessionStoreSetters.getSessionByTaskId(taskId);
    const editingId = currentSession?.editingQueuedId;
    if (
      editingId &&
      currentSession?.messageQueue.some((m) => m.id === editingId)
    ) {
      const result = await sessionService.cancelPrompt(taskId);
      log.info("Prompt cancelled during queued edit", { success: result });
      requestFocus(taskId);
      return;
    }

    const queuedMessages = sessionStoreSetters.dequeueMessages(taskId);
    const result = await sessionService.cancelPrompt(taskId);
    log.info("Prompt cancelled", { success: result });

    const queuedPrompt = sessionRef.current?.isCloud
      ? combineQueuedCloudPrompts(queuedMessages)
      : queuedMessages.map((message) => message.content).join("\n\n");

    if (queuedPrompt) {
      const pendingContent = sessionRef.current?.isCloud
        ? promptToQueuedEditorContent(queuedPrompt)
        : textToContent(typeof queuedPrompt === "string" ? queuedPrompt : "");

      setPendingContent(taskId, pendingContent);
    }
    requestFocus(taskId);
  }, [taskId, setPendingContent, requestFocus, sessionService]);

  const handleRetry = useCallback(async () => {
    try {
      if (sessionRef.current?.isCloud) {
        await sessionService.retryCloudTaskWatch(taskId);
        return;
      }

      if (!repoPath) return;
      await sessionService.clearSessionError(taskId, repoPath);
    } catch (error) {
      log.error("Failed to clear session error", error);
      toast.error("Failed to retry. Please try again.");
    }
  }, [taskId, repoPath, sessionService]);

  const handleNewSession = useCallback(async () => {
    if (!repoPath) return;
    try {
      await sessionService.resetSession(taskId, repoPath);
    } catch (error) {
      log.error("Failed to reset session", error);
      toast.error("Failed to start new session. Please try again.");
    }
  }, [taskId, repoPath, sessionService]);

  const handleBashCommand = useCallback(
    async (command: string) => {
      if (!repoPath) return;

      const execId = `user-shell-${Date.now()}-${Math.random().toString(36).slice(2, 9)}`;
      await sessionService.startUserShellExecute(
        taskId,
        execId,
        command,
        repoPath,
      );

      try {
        const result = await shellClient.execute({
          cwd: repoPath,
          command,
        });
        await sessionService.completeUserShellExecute(
          taskId,
          execId,
          command,
          repoPath,
          result,
        );
      } catch (error) {
        log.error("Failed to execute shell command", error);
        await sessionService.completeUserShellExecute(
          taskId,
          execId,
          command,
          repoPath,
          {
            stdout: "",
            stderr: error instanceof Error ? error.message : "Command failed",
            exitCode: 1,
          },
        );
      }
    },
    [taskId, repoPath, sessionService, shellClient],
  );

  const initiateHandoffToCloud = useCallback(async () => {
    if (!repoPath) return;
    try {
      await sessionService.handoffToCloud(taskId, repoPath);
    } catch (error) {
      log.error("Failed to hand off to cloud", error);
      const message = error instanceof Error ? error.message : "Unknown error";
      toast.error(`Failed to continue in cloud: ${message}`);
    }
  }, [taskId, repoPath, sessionService]);

  return {
    handleSendPrompt,
    handleCancelPrompt,
    handleRetry,
    handleNewSession,
    handleBashCommand,
    initiateHandoffToCloud,
  };
}
