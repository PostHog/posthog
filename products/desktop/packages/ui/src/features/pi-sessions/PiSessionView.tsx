import {
  contentToXml,
  isContentEmpty,
  textToContent,
  xmlToContent,
} from "@posthog/core/message-editor/content";
import {
  PI_EXTENSION_CONTROLLER,
  PI_SESSION_CONTROLLER,
} from "@posthog/core/pi-runtime/identifiers";
import type { PiExtensionController } from "@posthog/core/pi-runtime/piExtensionController";
import {
  createEmptyPiExtensionTaskState,
  type PiExtensionTaskState,
} from "@posthog/core/pi-runtime/piExtensionStore";
import {
  PiOperationError,
  type PiSessionController,
} from "@posthog/core/pi-runtime/piSessionController";
import type { PiControllerSessionState } from "@posthog/core/pi-runtime/piSessionStore";
import { toPiContextUsage } from "@posthog/core/pi-runtime/piSessionUsage";
import { useService } from "@posthog/di/react";
import {
  Button,
  Empty,
  EmptyContent,
  EmptyDescription,
  EmptyHeader,
  EmptyTitle,
  Skeleton,
} from "@posthog/quill";
import { MCP_TOOL_PERMISSION_OPTIONS } from "@posthog/shared";
import type { Task } from "@posthog/shared/domain-types";
import { useOptionalAuthenticatedClient } from "@posthog/ui/features/auth/authClient";
import { useCurrentUser } from "@posthog/ui/features/auth/useCurrentUser";
import { useUsageLimitStore } from "@posthog/ui/features/billing/usageLimitStore";
import {
  spendStopMessage,
  useSpendStop,
} from "@posthog/ui/features/billing/useSpendStop";
import { PromptInput } from "@posthog/ui/features/message-editor/components/PromptInput";
import { useDraftStore } from "@posthog/ui/features/message-editor/draftStore";
import { PermissionSelector } from "@posthog/ui/features/permissions/PermissionSelector";
import { CloudStreamDisconnectedBanner } from "@posthog/ui/features/sessions/components/CloudSessionLifecycle";
import { ContextUsageIndicator } from "@posthog/ui/features/sessions/components/ContextUsageIndicator";
import { ChatThread } from "@posthog/ui/features/sessions/components/chat-thread/ChatThread";
import type { PromptRecallHandler } from "@posthog/ui/features/sessions/components/chat-thread/composerPromptRecall";
import { CHAT_CONTENT_MAX_WIDTH } from "@posthog/ui/features/sessions/constants";
import { useMessagingModeStore } from "@posthog/ui/features/sessions/messagingModeStore";
import { useWorkspace } from "@posthog/ui/features/workspace/useWorkspace";
import { useConnectivity } from "@posthog/ui/hooks/useConnectivity";
import { toast } from "@posthog/ui/primitives/toast";
import { TaskDetailSkeleton } from "@posthog/ui/router/routeSkeletons";
import { logger } from "@posthog/ui/shell/logger";
import {
  type ReactElement,
  useCallback,
  useEffect,
  useRef,
  useState,
} from "react";
import { useStore } from "zustand";
import { PiExtensionDialog } from "./PiExtensionDialog";
import { PiExtensionStatuses, PiExtensionWidgets } from "./PiExtensionSurfaces";
import { PiQueuedMessagesDock } from "./PiQueuedMessagesDock";
import { PiMessagingModeSelector } from "./PiSessionControls";
import { PiSessionModelControls } from "./PiSessionModelControls";
import { buildPiMcpPermissionToolCall } from "./piMcpPermission";
import {
  getPiPendingConfig,
  usePiPendingConfigStore,
} from "./piPendingConfigStore";

const log = logger.scope("pi-session-view");

interface PiSessionViewProps {
  task: Task;
  isCloud: boolean;
}

type DraftActions = ReturnType<typeof useDraftStore.getState>["actions"];
type PendingConfig = ReturnType<typeof getPiPendingConfig>;
type ClearPendingConfig = ReturnType<
  typeof usePiPendingConfigStore.getState
>["clearConfig"];
type MessagingMode = Parameters<PiSessionController["getSubmitAction"]>[2];
type PiSubmitAction = ReturnType<PiSessionController["getSubmitAction"]>;
type PiQueueSnapshot = Awaited<ReturnType<PiSessionController["clearQueue"]>>;
type SetMessagingMode = ReturnType<
  typeof useMessagingModeStore.getState
>["setMode"];

function usePiSessionConnection(
  task: Task,
  isTaskAuthor: boolean | undefined,
): void {
  const controller = useService<PiSessionController>(PI_SESSION_CONTROLLER);
  const taskId = task.id;
  const taskRunId = task.latest_run?.id;

  useEffect(() => {
    controller.setNotificationContext(taskId, {
      taskTitle: task.title,
      isTaskAuthor,
    });
  }, [controller, isTaskAuthor, task.title, taskId]);

  useEffect(() => {
    void controller.ensureConnected(taskId, taskRunId).catch(() => {});
    return () => controller.release(taskId);
  }, [controller, taskId, taskRunId]);
}

function usePiExtensionConnection(
  taskId: string,
  taskRunId: string | undefined,
  isCloud: boolean,
  connectionState: PiControllerSessionState["connectionState"] | undefined,
): void {
  const controller = useService<PiExtensionController>(PI_EXTENSION_CONTROLLER);
  useEffect(() => {
    if (isCloud || connectionState !== "connected") {
      return;
    }
    void controller.connect(taskId, taskRunId).catch(() => {});
    return () => controller.disconnect(taskId);
  }, [connectionState, controller, isCloud, taskId, taskRunId]);
}

function usePiDraftContext(
  taskId: string,
  repoPath: string | undefined,
  isCompacting: boolean,
  isStreaming: boolean,
  isBashRunning: boolean,
): void {
  useEffect(() => {
    useDraftStore.getState().actions.setContext(taskId, {
      taskId,
      repoPath,
      disabled: isCompacting,
      isLoading: isStreaming || isBashRunning,
    });
  }, [isBashRunning, isCompacting, isStreaming, repoPath, taskId]);
}

function usePiCommands(
  taskId: string,
  commands: PiControllerSessionState["commands"] | undefined,
): void {
  useEffect(() => {
    if (!commands) {
      return;
    }

    const piCommands = commands.flatMap((command) =>
      command.name === "compact"
        ? []
        : [
            {
              name: command.name,
              description: command.description ?? "",
            },
          ],
    );

    useDraftStore.getState().actions.setCommands(taskId, [
      {
        name: "compact",
        description: "Compact the current Pi session context",
        input: { hint: "optional instructions" },
      },
      ...piCommands,
    ]);
  }, [commands, taskId]);
}

function usePiExtensionNotification(
  taskId: string,
  notification: PiExtensionTaskState["notifications"][number] | undefined,
): void {
  const controller = useService<PiExtensionController>(PI_EXTENSION_CONTROLLER);
  useEffect(() => {
    if (!notification) {
      return;
    }
    toast[notification.notifyType]("Pi extension", {
      description: notification.message,
    });
    controller.acknowledgeNotification(taskId, notification.id);
  }, [controller, notification, taskId]);
}

function usePiExtensionEditorText(
  taskId: string,
  editorText: PiExtensionTaskState["editorText"],
): void {
  const controller = useService<PiExtensionController>(PI_EXTENSION_CONTROLLER);
  useEffect(() => {
    if (!editorText) {
      return;
    }
    const draftActions = useDraftStore.getState().actions;
    draftActions.setPendingContent(taskId, textToContent(editorText.text));
    draftActions.requestFocus(taskId);
    controller.acknowledgeEditorText(taskId, editorText.id);
  }, [controller, editorText, taskId]);
}

function usePiExtensionTitle(title: PiExtensionTaskState["title"]): void {
  useEffect(() => {
    if (title === undefined) {
      return;
    }
    const previousTitle = document.title;
    document.title = title;
    return () => {
      document.title = previousTitle;
    };
  }, [title]);
}

function usePiRecoveryPrompt(
  taskId: string,
  failure: PiControllerSessionState["error"],
): void {
  useEffect(() => {
    if (
      failure?.scope !== "operation" ||
      !failure.recoveryPrompt ||
      !isContentEmpty(useDraftStore.getState().drafts[taskId] ?? null)
    ) {
      return;
    }
    const draftActions = useDraftStore.getState().actions;
    draftActions.setPendingContent(
      taskId,
      xmlToContent(failure.recoveryPrompt),
    );
    draftActions.requestFocus(taskId);
  }, [failure, taskId]);
}

function usePiFailureNotice(failure: PiControllerSessionState["error"]): void {
  useEffect(() => {
    if (!failure || failure.scope !== "operation") {
      return;
    }
    if (failure.kind === "usage_limit") {
      useUsageLimitStore
        .getState()
        .show(failure.limitCause ? { cause: failure.limitCause } : undefined);
    } else {
      toast.error(failure.title, { description: failure.message });
    }
  }, [failure]);
}

function usePiFailureAcknowledgement(
  taskId: string,
  failure: PiControllerSessionState["error"],
): void {
  const controller = useService<PiSessionController>(PI_SESSION_CONTROLLER);
  useEffect(() => {
    if (failure?.scope === "operation") {
      controller.acknowledgeOperationFailure(taskId, failure.id);
    }
  }, [controller, failure, taskId]);
}

function handleControllerError(error: unknown, fallback: string): void {
  log.error(fallback, error);
  if (!(error instanceof PiOperationError)) {
    toast.error(fallback);
  }
}

function applyPiSubmitResult(
  action: PiSubmitAction,
  pendingConfig: PendingConfig,
  clearPendingConfig: ClearPendingConfig,
  taskId: string,
  taskRunId: string | undefined,
): void {
  if (action === "prompt" && pendingConfig && taskRunId) {
    clearPendingConfig(taskId, taskRunId);
  }
  if (action === "compact") {
    toast.success("Pi context compacted");
  }
}

function applyQueueToDraft(
  queue: PiQueueSnapshot,
  draftActions: DraftActions,
  taskId: string,
): void {
  const queuedText = [...queue.steering, ...queue.followUp].join("\n\n");
  if (!queuedText) {
    return;
  }
  const draft = draftActions.getDraft(taskId);
  const draftText =
    typeof draft === "string" ? draft : draft ? contentToXml(draft) : "";
  const content = [queuedText, draftText]
    .filter((value) => value.trim())
    .join("\n\n");
  draftActions.setPendingContent(taskId, xmlToContent(content));
  draftActions.requestFocus(taskId);
}

function usePiSubmit(
  controller: PiSessionController,
  taskId: string,
  pendingConfig: PendingConfig,
  messagingMode: MessagingMode,
  isStreaming: boolean,
  onSuccess: (action: PiSubmitAction) => void,
) {
  return useCallback(
    (text: string) => {
      const message = text.trim();
      if (!message) {
        return;
      }

      const action = controller.getSubmitAction(
        message,
        isStreaming,
        messagingMode,
      );
      void controller
        .submit(taskId, message, isStreaming, messagingMode, pendingConfig)
        .then(() => {
          onSuccess(action);
        })
        .catch((error) => {
          handleControllerError(
            error,
            action === "compact"
              ? "Failed to compact Pi context"
              : "Failed to send message to Pi",
          );
        });
    },
    [controller, isStreaming, messagingMode, onSuccess, pendingConfig, taskId],
  );
}

function usePiMessagingModeToggle(
  setMessagingMode: SetMessagingMode,
  taskId: string,
  messagingMode: MessagingMode,
) {
  return useCallback(() => {
    setMessagingMode(taskId, messagingMode === "steer" ? "queue" : "steer");
  }, [messagingMode, setMessagingMode, taskId]);
}

function usePiBash(
  controller: PiSessionController,
  taskId: string,
): (command: string) => void {
  return useCallback(
    (command: string) => {
      void controller
        .bash(taskId, command)
        .catch((error) =>
          handleControllerError(error, "Failed to run Pi bash command"),
        );
    },
    [controller, taskId],
  );
}

function usePiCancel(
  controller: PiSessionController,
  taskId: string,
  isBashRunning: boolean,
): () => void {
  return useCallback(() => {
    const cancellation = isBashRunning
      ? controller.abortBash(taskId)
      : controller.abort(taskId);
    void cancellation.catch((error) =>
      handleControllerError(
        error,
        isBashRunning ? "Failed to stop bash" : "Failed to stop Pi",
      ),
    );
  }, [controller, isBashRunning, taskId]);
}

function usePiRetry(
  controller: PiSessionController,
  taskId: string,
): () => void {
  return useCallback(() => {
    void controller
      .retry(taskId)
      .catch((error) =>
        handleControllerError(error, "Failed to reconnect to Pi"),
      );
  }, [controller, taskId]);
}

function usePiRestart(
  controller: PiSessionController,
  taskId: string,
): () => void {
  return useCallback(() => {
    void controller
      .restart(taskId)
      .catch((error) => handleControllerError(error, "Failed to restart Pi"));
  }, [controller, taskId]);
}

function usePiEditQueue(
  controller: PiSessionController,
  taskId: string,
  onQueue: (queue: PiQueueSnapshot) => void,
): () => void {
  return useCallback(() => {
    void controller
      .clearQueue(taskId)
      .then(onQueue)
      .catch((error) =>
        handleControllerError(error, "Failed to edit queued Pi message"),
      );
  }, [controller, onQueue, taskId]);
}

function usePiRemoveQueue(
  controller: PiSessionController,
  taskId: string,
): () => void {
  return useCallback(() => {
    void controller
      .clearQueue(taskId)
      .catch((error) =>
        handleControllerError(error, "Failed to discard queued Pi message"),
      );
  }, [controller, taskId]);
}

export function PiSessionView({ task, isCloud }: PiSessionViewProps) {
  const taskId = task.id;
  const taskRunId = task.latest_run?.id;
  const authenticatedClient = useOptionalAuthenticatedClient();
  const { data: currentUser } = useCurrentUser({ client: authenticatedClient });
  const isTaskAuthor =
    currentUser?.uuid && task.created_by?.uuid
      ? currentUser.uuid === task.created_by.uuid
      : undefined;
  const piSessionController = useService<PiSessionController>(
    PI_SESSION_CONTROLLER,
  );
  const piExtensionController = useService<PiExtensionController>(
    PI_EXTENSION_CONTROLLER,
  );
  const session = useStore(
    piSessionController.store,
    (state) => state.sessions[taskId],
  );
  const extensionState = useStore(
    piExtensionController.store,
    (state) => state.tasks[taskId],
  );
  const draftActions = useDraftStore((state) => state.actions);
  const pendingConfig = usePiPendingConfigStore((state) =>
    getPiPendingConfig(state, taskId, taskRunId),
  );
  const clearPendingConfig = usePiPendingConfigStore(
    (state) => state.clearConfig,
  );
  const workspace = useWorkspace(taskId);
  const repoPath = workspace?.worktreePath ?? workspace?.folderPath;
  const messagingMode = useMessagingModeStore(
    (state) => state.modesByTaskId[taskId] ?? "steer",
  );
  const setMessagingMode = useMessagingModeStore((state) => state.setMode);
  const { isOnline } = useConnectivity();
  const promptRecallRef = useRef<PromptRecallHandler | null>(null);
  const mcpPermissionResponsePending = useRef(false);
  const [isMcpPermissionResponding, setIsMcpPermissionResponding] =
    useState(false);
  const handlePromptRecall = useCallback<PromptRecallHandler>(
    (direction) => promptRecallRef.current?.(direction) ?? null,
    [],
  );

  usePiSessionConnection(task, isTaskAuthor);
  usePiExtensionConnection(
    taskId,
    taskRunId,
    isCloud,
    session?.connectionState,
  );

  const status = session?.status;
  const isStreaming = status?.isStreaming ?? false;
  const isCompacting = status?.isCompacting ?? false;
  const isBashRunning = session?.isBashRunning ?? false;

  usePiDraftContext(taskId, repoPath, isCompacting, isStreaming, isBashRunning);
  usePiCommands(taskId, session?.commands);

  const handleSubmitSuccess = useCallback(
    (action: PiSubmitAction) =>
      applyPiSubmitResult(
        action,
        pendingConfig,
        clearPendingConfig,
        taskId,
        taskRunId,
      ),
    [clearPendingConfig, pendingConfig, taskId, taskRunId],
  );
  const sendPrompt = usePiSubmit(
    piSessionController,
    taskId,
    pendingConfig,
    messagingMode,
    isStreaming,
    handleSubmitSuccess,
  );
  const toggleMessagingMode = usePiMessagingModeToggle(
    setMessagingMode,
    taskId,
    messagingMode,
  );
  const runBashCommand = usePiBash(piSessionController, taskId);
  const cancelPrompt = usePiCancel(piSessionController, taskId, isBashRunning);
  const retry = usePiRetry(piSessionController, taskId);
  const restart = usePiRestart(piSessionController, taskId);
  const handleQueueForEditing = useCallback(
    (queue: PiQueueSnapshot) => applyQueueToDraft(queue, draftActions, taskId),
    [draftActions, taskId],
  );
  const editQueuedMessage = usePiEditQueue(
    piSessionController,
    taskId,
    handleQueueForEditing,
  );
  const removeQueuedMessage = usePiRemoveQueue(piSessionController, taskId);

  usePiExtensionNotification(taskId, extensionState?.notifications[0]);
  usePiExtensionEditorText(taskId, extensionState?.editorText);
  usePiExtensionTitle(extensionState?.title);
  usePiRecoveryPrompt(taskId, session?.error);
  usePiFailureNotice(session?.error);
  usePiFailureAcknowledgement(taskId, session?.error);

  const mcpPermission = session?.mcpToolPermissionRequests
    .values()
    .next().value;
  const respondMcpPermission = useCallback(
    (decision: "allow_always" | "reject") => {
      if (!mcpPermission || mcpPermissionResponsePending.current) {
        return;
      }

      mcpPermissionResponsePending.current = true;
      setIsMcpPermissionResponding(true);
      void piSessionController
        .respondMcpToolPermission(taskId, mcpPermission, decision)
        .catch((error) =>
          log.error("Failed to respond to MCP permission", error),
        )
        .finally(() => {
          mcpPermissionResponsePending.current = false;
          setIsMcpPermissionResponding(false);
        });
    },
    [mcpPermission, piSessionController, taskId],
  );

  const spendStop = useSpendStop();

  if (!session) {
    return <TaskDetailSkeleton />;
  }

  const isConnecting = session.connectionState === "connecting";
  const isAuthRestoring = session.authRestoring;
  const connectionError =
    session.error?.scope === "connection" ? session.error : undefined;
  const contextUsage = toPiContextUsage(session.stats);
  const hasTranscript = session.events.some(
    (event) => event.type !== "progress",
  );
  const sessionAvailable =
    session.connectionState === "connected" || hasTranscript;
  if (connectionError && !hasTranscript) {
    return (
      <Empty className="h-full">
        <EmptyHeader>
          <EmptyTitle>{connectionError.title}</EmptyTitle>
          <EmptyDescription>{connectionError.message}</EmptyDescription>
        </EmptyHeader>
        <EmptyContent>
          {connectionError.retryable && (
            <Button variant="primary" onClick={retry}>
              Retry
            </Button>
          )}
          <Button variant="outline" onClick={restart}>
            Restart
          </Button>
        </EmptyContent>
      </Empty>
    );
  }

  if (!status && !hasTranscript && (!isConnecting || !isCloud)) {
    return <TaskDetailSkeleton />;
  }

  const controlsPending = status ? isStreaming || isBashRunning : false;
  const hasQueuedMessage =
    session.queue.steering.length + session.queue.followUp.length > 0;
  let messagingModeToggle: ReactElement = (
    <Skeleton className="h-7 w-24 bg-foreground/15" />
  );

  if (status) {
    messagingModeToggle = (
      <PiMessagingModeSelector
        mode={messagingMode}
        queuedCount={status.pendingMessageCount}
        disabled={isBashRunning}
        onModeChange={(mode) => setMessagingMode(taskId, mode)}
      />
    );
  }

  const currentExtensionState =
    extensionState ?? createEmptyPiExtensionTaskState();
  const extensionDialog = currentExtensionState.dialogs[0];

  return (
    <div className="flex h-full flex-col">
      {extensionDialog && (
        <PiExtensionDialog
          key={extensionDialog.id}
          request={extensionDialog}
          onRespond={(response) =>
            piExtensionController.respondToExtensionUI(taskId, response)
          }
          onCancel={() =>
            piExtensionController.cancelExtensionUI(taskId, extensionDialog.id)
          }
        />
      )}
      {connectionError && hasTranscript && (
        <CloudStreamDisconnectedBanner
          errorTitle={connectionError.title}
          errorMessage={connectionError.message}
          onRetry={connectionError.retryable ? retry : undefined}
          onRestart={restart}
        />
      )}
      <div className="min-h-0 flex-1">
        <ChatThread
          events={session.events}
          isPromptPending={isStreaming}
          taskId={taskId}
          repoPath={repoPath}
          promptRecallRef={promptRecallRef}
          hasPendingPermission={Boolean(mcpPermission)}
        />
      </div>
      <div
        className="mx-auto w-full px-2 pb-3"
        style={{ maxWidth: CHAT_CONTENT_MAX_WIDTH }}
      >
        <PiQueuedMessagesDock
          queue={session.queue}
          onEdit={editQueuedMessage}
          onRemove={removeQueuedMessage}
        />
        {!isCloud && (
          <>
            <PiExtensionStatuses statuses={currentExtensionState.statuses} />
            <PiExtensionWidgets
              widgets={currentExtensionState.widgets}
              placement="aboveEditor"
            />
          </>
        )}
        {mcpPermission ? (
          isMcpPermissionResponding ? (
            <Skeleton className="h-24 w-full" />
          ) : (
            <PermissionSelector
              toolCall={buildPiMcpPermissionToolCall(mcpPermission)}
              options={[...MCP_TOOL_PERMISSION_OPTIONS]}
              onSelect={(optionId) => {
                respondMcpPermission(
                  optionId === "allow_always" ? "allow_always" : "reject",
                );
              }}
              onCancel={() => respondMcpPermission("reject")}
            />
          )
        ) : (
          <PromptInput
            sessionId={taskId}
            toolbarEndSlot={
              <ContextUsageIndicator usage={contextUsage} taskId={taskId} />
            }
            taskId={taskId}
            repoPath={repoPath}
            placeholder="Type a message..."
            disabled={isCompacting}
            isLoading={controlsPending}
            submitDisabledExternal={
              !sessionAvailable ||
              !status ||
              !isOnline ||
              hasQueuedMessage ||
              isAuthRestoring ||
              spendStop !== null
            }
            submitTooltipOverride={
              !isOnline
                ? "No internet connection"
                : isAuthRestoring
                  ? "Restoring authentication"
                  : hasQueuedMessage
                    ? "A message is already queued"
                    : spendStop
                      ? spendStopMessage(spendStop)
                      : undefined
            }
            enableBashMode
            enableCommands
            modelSelector={
              <PiSessionModelControls
                taskId={taskId}
                taskRunId={taskRunId}
                session={session}
                controller={piSessionController}
                isOnline={isOnline}
                onError={handleControllerError}
              />
            }
            reasoningSelector={null}
            messagingModeToggle={messagingModeToggle}
            onToggleMessagingMode={toggleMessagingMode}
            onPromptRecall={handlePromptRecall}
            onSubmit={sendPrompt}
            onBashCommand={runBashCommand}
            onCancel={cancelPrompt}
          />
        )}
        {!isCloud && (
          <PiExtensionWidgets
            widgets={currentExtensionState.widgets}
            placement="belowEditor"
          />
        )}
      </div>
    </div>
  );
}
