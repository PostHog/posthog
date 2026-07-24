import { Pause, Spinner, Warning } from "@phosphor-icons/react";
import {
  createLatestPlanTracker,
  SESSION_SERVICE,
  type SessionService,
} from "@posthog/core/sessions/sessionService";
import { useService } from "@posthog/di/react";
import type { AcpMessage } from "@posthog/shared";
import type { Task, TaskRunStatus } from "@posthog/shared/domain-types";
import { showOfflineToast } from "@posthog/ui/features/connectivity/connectivityToast";
import {
  PromptInput,
  type EditorHandle as PromptInputHandle,
} from "@posthog/ui/features/message-editor/components/PromptInput";
import { useDraftStore } from "@posthog/ui/features/message-editor/draftStore";
import { useAutoFocusOnTyping } from "@posthog/ui/features/message-editor/useAutoFocusOnTyping";
import { resolveAndAttachDroppedFiles } from "@posthog/ui/features/message-editor/utils/persistFile";
import { PermissionSelector } from "@posthog/ui/features/permissions/PermissionSelector";
import { CloudInitializingView } from "@posthog/ui/features/sessions/components/CloudInitializingView";
import type { PromptRecallHandler } from "@posthog/ui/features/sessions/components/chat-thread/composerPromptRecall";
import {
  copyFromContextMenu,
  getGithubRefUrlFromEventTarget,
} from "@posthog/ui/features/sessions/components/copyContextTarget";
import { DropZoneOverlay } from "@posthog/ui/features/sessions/components/DropZoneOverlay";
import { ModelSelector } from "@posthog/ui/features/sessions/components/ModelSelector";
import { PendingChatView } from "@posthog/ui/features/sessions/components/PendingChatView";
import { PlanStatusBar } from "@posthog/ui/features/sessions/components/PlanStatusBar";
import { QueuedMessagesDock } from "@posthog/ui/features/sessions/components/QueuedMessagesDock";
import { ReasoningLevelSelector } from "@posthog/ui/features/sessions/components/ReasoningLevelSelector";
import { RawLogsView } from "@posthog/ui/features/sessions/components/raw-logs/RawLogsView";
import { SessionResourcesBar } from "@posthog/ui/features/sessions/components/SessionResourcesBar";
import { SteerQueueToggle } from "@posthog/ui/features/sessions/components/SteerQueueToggle";
import {
  isSubmittedContentUnchanged,
  shouldSubmitComposerOptimistically,
  submitComposerPrompt,
} from "@posthog/ui/features/sessions/components/submitComposerPrompt";
import { ThreadView } from "@posthog/ui/features/sessions/components/ThreadView";
import { CHAT_CONTENT_MAX_WIDTH } from "@posthog/ui/features/sessions/constants";
import { useCancelQueuedMessageEdit } from "@posthog/ui/features/sessions/hooks/useEditQueuedMessage";
import { useSessionEventsResidency } from "@posthog/ui/features/sessions/hooks/useSessionEventsResidency";
import { useToggleMessagingMode } from "@posthog/ui/features/sessions/hooks/useToggleMessagingMode";
import {
  useAdapterForTask,
  useModeConfigOptionForTask,
  usePendingPermissionsForTask,
  useSessionSelector,
  useThoughtLevelConfigOptionForTask,
} from "@posthog/ui/features/sessions/sessionStore";
import {
  useSessionViewActions,
  useShowRawLogs,
} from "@posthog/ui/features/sessions/sessionViewStore";
import type { Plan } from "@posthog/ui/features/sessions/types";
import { useSessionHandoffInProgress } from "@posthog/ui/features/sessions/useSession";
import { useSettingsStore } from "@posthog/ui/features/settings/settingsStore";
import { useIsWorkspaceCloudRun } from "@posthog/ui/features/workspace/useWorkspace";
import { useConnectivity } from "@posthog/ui/hooks/useConnectivity";
import { toast } from "@posthog/ui/primitives/toast";
import {
  pendingTaskPromptStoreApi,
  usePendingTaskPrompt,
} from "@posthog/ui/shell/pendingTaskPromptStore";
import { Box, Button, ContextMenu, Flex, Text } from "@radix-ui/themes";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";

interface SessionViewProps {
  events: AcpMessage[];
  taskId?: string;
  task?: Task;
  isRunning: boolean;
  isPromptPending?: boolean | null;
  promptStartedAt?: number | null;
  onBeforeSubmit?: (text: string, clearEditor: () => void) => boolean;
  onSendPrompt: (text: string) => Promise<boolean>;
  onBashCommand?: (command: string) => void;
  onCancelPrompt: () => void;
  repoPath?: string | null;
  cloudBranch?: string | null;
  isSuspended?: boolean;
  onRestoreWorktree?: () => void;
  isRestoring?: boolean;
  hasError?: boolean;
  errorTitle?: string;
  errorMessage?: string;
  errorRetryable?: boolean;
  onRetry?: () => void;
  onNewSession?: () => void;
  isInitializing?: boolean;
  isCloud?: boolean;
  cloudStatus?: TaskRunStatus | null;
  slackThreadUrl?: string;
  compact?: boolean;
  isActiveSession?: boolean;
  /** Hide the message input and permission UI — log-only view. */
  hideInput?: boolean;
}

const DEFAULT_ERROR_MESSAGE =
  "Failed to resume this session. The working directory may have been deleted. Please start a new session.";

function ConnectingToAgent() {
  return (
    <>
      <Spinner size={28} className="animate-spin text-gray-9" />
      <Text color="gray" className="text-base">
        Connecting to agent...
      </Text>
    </>
  );
}

/** Centers composer-slot content at the chat width (or compact padding). */
function ComposerWidth({
  compact,
  children,
}: {
  compact: boolean;
  children: React.ReactNode;
}) {
  return (
    <Box
      className={compact ? "p-1" : "mx-auto px-2 pb-3"}
      style={compact ? undefined : { maxWidth: CHAT_CONTENT_MAX_WIDTH }}
    >
      {children}
    </Box>
  );
}

/**
 * Input region replacing the composer: `shrink-0` keeps it from being
 * compressed by the scroller above, and `min-h-0 overflow-y-auto` lets tall
 * content scroll inside itself.
 */
function ComposerSlot({
  compact,
  children,
}: {
  compact: boolean;
  children: React.ReactNode;
}) {
  return (
    <Box
      className={
        compact
          ? "max-h-[50%] min-h-0 overflow-y-auto"
          : "min-h-0 shrink-0 overflow-y-auto"
      }
    >
      <ComposerWidth compact={compact}>{children}</ComposerWidth>
    </Box>
  );
}

interface CloudStreamDisconnectedBannerProps {
  errorTitle?: string;
  errorMessage?: string;
  onRetry?: () => void;
}

function CloudStreamDisconnectedBanner({
  errorTitle,
  errorMessage,
  onRetry,
}: CloudStreamDisconnectedBannerProps) {
  return (
    <Flex
      align="center"
      justify="between"
      gap="3"
      py="2"
      px="3"
      className="shrink-0 border-(--red-5) border-b bg-(--red-2)"
    >
      <Flex align="center" gap="2" className="min-w-0">
        <Warning size={14} weight="duotone" color="var(--red-9)" />
        {errorTitle && (
          <Text className="shrink-0 font-medium text-(--red-12) text-[13px]">
            {errorTitle}
          </Text>
        )}
        {errorMessage && (
          <Text color="gray" className="truncate text-[13px]">
            {errorMessage}
          </Text>
        )}
      </Flex>
      {onRetry && (
        <Button variant="soft" size="1" color="red" onClick={onRetry}>
          Retry
        </Button>
      )}
    </Flex>
  );
}

export function SessionView({
  events,
  taskId,
  task,
  isRunning,
  isPromptPending = false,
  promptStartedAt,
  onBeforeSubmit,
  onSendPrompt,
  onBashCommand,
  onCancelPrompt,
  repoPath,
  cloudBranch,
  isSuspended = false,
  onRestoreWorktree,
  isRestoring = false,
  hasError = false,
  errorTitle,
  errorMessage = DEFAULT_ERROR_MESSAGE,
  errorRetryable = false,
  onRetry,
  onNewSession,
  isInitializing = false,
  isCloud = false,
  cloudStatus = null,
  slackThreadUrl,
  compact = false,
  isActiveSession = true,
  hideInput = false,
}: SessionViewProps) {
  const sessionService = useService<SessionService>(SESSION_SERVICE);
  useSessionEventsResidency(taskId);
  const showRawLogs = useShowRawLogs();
  const { setShowRawLogs } = useSessionViewActions();
  const pendingTaskPrompt = usePendingTaskPrompt(taskId);
  const pendingPermissions = usePendingPermissionsForTask(taskId);
  const modeOption = useModeConfigOptionForTask(taskId);
  const thoughtOption = useThoughtLevelConfigOptionForTask(taskId);
  const adapter = useAdapterForTask(taskId);
  const toggleMessagingMode = useToggleMessagingMode(taskId);
  const { allowBypassPermissions } = useSettingsStore();
  const useNewChatThread = useSettingsStore((s) => s.useNewChatThread);
  const { isOnline } = useConnectivity();
  const currentModeId = modeOption?.currentValue;
  const handoffInProgress = useSessionHandoffInProgress(taskId);
  const showInlineBanner = hasError && errorRetryable && events.length > 0;

  useEffect(() => {
    if (!taskId) return;
    if (isInitializing) return;
    pendingTaskPromptStoreApi.clear(taskId);
  }, [taskId, isInitializing]);

  useEffect(() => {
    sessionService.maybeRevertBypassMode(taskId, {
      isCloud,
      allowBypassPermissions,
      currentModeId,
      modeOption,
    });
  }, [
    allowBypassPermissions,
    currentModeId,
    taskId,
    isCloud,
    sessionService,
    modeOption,
  ]);

  const handleModeChange = useCallback(
    (nextMode: string) => {
      if (!taskId) return;
      sessionService.setSessionConfigOptionByCategory(taskId, "mode", nextMode);
    },
    [taskId, sessionService],
  );

  const handleThoughtChange = useCallback(
    (value: string) => {
      if (!taskId || !thoughtOption) return;
      sessionService.setSessionConfigOption(taskId, thoughtOption.id, value);
    },
    [taskId, thoughtOption, sessionService],
  );

  const sessionId = taskId ?? "default";
  const setContext = useDraftStore((s) => s.actions.setContext);
  const requestFocus = useDraftStore((s) => s.actions.requestFocus);

  useEffect(() => {
    setContext(sessionId, {
      taskId,
      repoPath,
      cloudBranch,
      disabled: !isRunning,
      isLoading: !!isPromptPending,
    });
  }, [
    setContext,
    sessionId,
    taskId,
    repoPath,
    cloudBranch,
    isRunning,
    isPromptPending,
  ]);

  const isCloudRun = useIsWorkspaceCloudRun(taskId);
  const editorRef = useRef<PromptInputHandle>(null);
  const sendInFlightRef = useRef(false);
  const composerSubmissionRef = useRef(0);

  const latestPlanTrackerRef = useRef<ReturnType<
    typeof createLatestPlanTracker
  > | null>(null);
  latestPlanTrackerRef.current ??= createLatestPlanTracker();
  const latestPlanTracker = latestPlanTrackerRef.current;
  const latestPlan = useMemo(
    (): Plan | null => latestPlanTracker.update(events) as Plan | null,
    [events, latestPlanTracker],
  );
  const handleSubmit = useCallback(
    async (text: string): Promise<void> => {
      if (!text.trim() || sendInFlightRef.current) return;

      sendInFlightRef.current = true;
      const submissionId = ++composerSubmissionRef.current;
      const editor = editorRef.current;
      const submittedContent = editor?.getContent() ?? null;
      if (
        editor &&
        shouldSubmitComposerOptimistically(submittedContent, text)
      ) {
        const sendPromise = submitComposerPrompt(
          editor,
          submittedContent,
          () => onSendPrompt(text),
          () => submissionId === composerSubmissionRef.current,
        );
        sendInFlightRef.current = false;
        await sendPromise;
        return;
      }

      try {
        if (await onSendPrompt(text)) {
          const currentEditor = editorRef.current;
          if (
            currentEditor &&
            isSubmittedContentUnchanged(currentEditor.getContent(), text)
          ) {
            currentEditor.clear();
          }
        }
      } finally {
        sendInFlightRef.current = false;
      }
    },
    [onSendPrompt],
  );

  const handleBeforeSubmit = useCallback(
    (text: string, clearEditor: () => void): boolean => {
      if (!isOnline) {
        showOfflineToast();
        return false;
      }
      return onBeforeSubmit ? onBeforeSubmit(text, clearEditor) : true;
    },
    [isOnline, onBeforeSubmit],
  );

  const isEditingQueued = useSessionSelector(
    taskId,
    (s) => !!s?.editingQueuedId,
  );
  const cancelQueuedEdit = useCancelQueuedMessageEdit(taskId);

  const [isDraggingFile, setIsDraggingFile] = useState(false);
  const promptRecallRef = useRef<PromptRecallHandler | null>(null);
  const handlePromptRecall = useCallback<PromptRecallHandler>(
    (direction) => promptRecallRef.current?.(direction) ?? null,
    [],
  );
  const dragCounterRef = useRef(0);
  // URL of the GitHub chip the context menu was opened on, captured on
  // right-click so the "Copy" item can copy the link (selections can't reach it).
  const copyTargetUrlRef = useRef<string | null>(null);

  const firstPendingPermission = useMemo(() => {
    const entries = Array.from(pendingPermissions.entries());
    if (entries.length === 0) return null;
    const [toolCallId, permission] = entries[0];
    return { ...permission, toolCallId };
  }, [pendingPermissions]);

  const handlePermissionSelect = useCallback(
    async (
      optionId: string,
      customInput?: string,
      answers?: Record<string, string>,
    ) => {
      if (!firstPendingPermission || !taskId) return;

      const plan = await sessionService.resolvePermissionSelection(
        taskId,
        firstPendingPermission,
        optionId,
        modeOption,
        customInput,
        answers,
      );

      if (plan.resendPromptText) {
        onSendPrompt(plan.resendPromptText);
      }

      requestFocus(sessionId);
    },
    [
      firstPendingPermission,
      taskId,
      onSendPrompt,
      requestFocus,
      sessionId,
      modeOption,
      sessionService,
    ],
  );

  const handlePermissionCancel = useCallback(async () => {
    if (!firstPendingPermission || !taskId) return;
    await sessionService.cancelPermissionAndPrompt(
      taskId,
      firstPendingPermission.toolCallId,
    );
    requestFocus(sessionId);
  }, [firstPendingPermission, taskId, requestFocus, sessionId, sessionService]);

  const handleDragEnter = useCallback((e: React.DragEvent) => {
    e.preventDefault();
    e.stopPropagation();
    dragCounterRef.current++;
    if (e.dataTransfer.types.includes("Files")) {
      setIsDraggingFile(true);
    }
  }, []);

  const handleDragLeave = useCallback((e: React.DragEvent) => {
    e.preventDefault();
    e.stopPropagation();
    dragCounterRef.current--;
    if (dragCounterRef.current === 0) {
      setIsDraggingFile(false);
    }
  }, []);

  const handleDragOver = useCallback((e: React.DragEvent) => {
    e.preventDefault();
    e.stopPropagation();
  }, []);

  const handleDrop = useCallback((e: React.DragEvent) => {
    e.preventDefault();
    e.stopPropagation();
    dragCounterRef.current = 0;
    setIsDraggingFile(false);

    // If dropped on the editor, Tiptap's handleDrop already handled it
    if ((e.target as HTMLElement).closest(".ProseMirror")) return;

    const files = e.dataTransfer.files;
    if (!files || files.length === 0) return;

    resolveAndAttachDroppedFiles(files, (a) =>
      editorRef.current?.addAttachment(a),
    )
      .then(() => editorRef.current?.focus())
      .catch(() => toast.error("Failed to attach files"));
  }, []);

  const handlePaneClick = useCallback((e: React.MouseEvent) => {
    const target = e.target as HTMLElement;

    const interactiveSelector =
      'button, a, input, textarea, select, [role="button"], [role="link"], [contenteditable="true"], [data-interactive]';
    if (target.closest(interactiveSelector)) {
      return;
    }

    const selection = window.getSelection();
    if (selection && selection.toString().length > 0) {
      return;
    }

    editorRef.current?.focus();
  }, []);

  useAutoFocusOnTyping(editorRef, !isActiveSession);

  const handleContextMenu = useCallback((e: React.MouseEvent) => {
    const target = e.target as HTMLElement;
    if (
      target.closest('input, textarea, [contenteditable="true"], .ProseMirror')
    ) {
      e.stopPropagation();
      return;
    }
    copyTargetUrlRef.current = getGithubRefUrlFromEventTarget(e.target);
  }, []);

  return (
    <ContextMenu.Root>
      <ContextMenu.Trigger>
        {showRawLogs ? (
          <Flex
            direction="column"
            height="100%"
            className="relative bg-background"
            onContextMenu={handleContextMenu}
          >
            <RawLogsView
              events={events}
              onClose={() => setShowRawLogs(false)}
            />
          </Flex>
        ) : (
          <Flex
            direction="column"
            height="100%"
            className="relative bg-background"
            onClick={handlePaneClick}
            onContextMenu={handleContextMenu}
            onDragEnter={handleDragEnter}
            onDragLeave={handleDragLeave}
            onDragOver={handleDragOver}
            onDrop={handleDrop}
          >
            {isSuspended ? (
              <>
                <ThreadView
                  events={events}
                  isPromptPending={isPromptPending}
                  promptStartedAt={promptStartedAt}
                  repoPath={repoPath}
                  taskId={taskId}
                  task={task}
                  slackThreadUrl={slackThreadUrl}
                  scrollX={false}
                />
                <Box className="border-gray-4 border-t">
                  <Box
                    className="mx-auto px-2 pb-3"
                    style={{ maxWidth: CHAT_CONTENT_MAX_WIDTH }}
                  >
                    <Flex
                      align="center"
                      justify="between"
                      gap="3"
                      py="2"
                      px="3"
                      className="rounded-2 bg-gray-3"
                    >
                      <Flex align="center" gap="2">
                        <Pause
                          size={14}
                          weight="duotone"
                          color="var(--gray-11)"
                        />
                        <Text className="font-medium text-[13px]">
                          Worktree suspended
                        </Text>
                        <Text color="gray" className="text-[13px]">
                          Worktree was removed to save disk space
                        </Text>
                      </Flex>
                      {onRestoreWorktree && (
                        <Button
                          variant="outline"
                          size="1"
                          onClick={onRestoreWorktree}
                          disabled={isRestoring}
                        >
                          {isRestoring ? (
                            <>
                              <Spinner size={14} className="animate-spin" />
                              Restoring...
                            </>
                          ) : (
                            "Restore worktree"
                          )}
                        </Button>
                      )}
                    </Flex>
                  </Box>
                </Box>
              </>
            ) : isInitializing ? (
              isCloud ? (
                <CloudInitializingView cloudStatus={cloudStatus} />
              ) : pendingTaskPrompt?.promptText ? (
                <PendingChatView
                  promptText={pendingTaskPrompt.promptText}
                  attachments={pendingTaskPrompt.attachments}
                />
              ) : (
                <Flex
                  align="center"
                  justify="center"
                  className="absolute inset-0 bg-background"
                >
                  <Spinner size={32} className="animate-spin text-gray-9" />
                </Flex>
              )
            ) : (
              <>
                <DropZoneOverlay isVisible={isDraggingFile} />
                {showInlineBanner && (
                  <CloudStreamDisconnectedBanner
                    errorTitle={errorTitle}
                    errorMessage={errorMessage}
                    onRetry={onRetry}
                  />
                )}
                <ThreadView
                  events={events}
                  isPromptPending={isPromptPending}
                  promptStartedAt={promptStartedAt}
                  repoPath={repoPath}
                  taskId={taskId}
                  task={task}
                  slackThreadUrl={slackThreadUrl}
                  compact={compact}
                  scrollX={false}
                  promptRecallRef={promptRecallRef}
                />

                {!useNewChatThread && <SessionResourcesBar events={events} />}

                <PlanStatusBar plan={latestPlan} />

                {hasError && !showInlineBanner ? (
                  <Flex
                    align="center"
                    justify="center"
                    direction="column"
                    gap="2"
                    className="absolute inset-0 bg-background"
                  >
                    <Warning size={32} weight="duotone" color="var(--red-9)" />
                    {errorTitle && (
                      <Text
                        align="center"
                        color="red"
                        className="font-bold text-base"
                      >
                        {errorTitle}
                      </Text>
                    )}
                    <Text
                      align="center"
                      color={errorTitle ? "gray" : "red"}
                      className={`max-w-md px-4 ${errorTitle ? "text-sm" : "font-medium text-base"}`}
                    >
                      {errorMessage}
                    </Text>
                    <Flex gap="2" mt="2">
                      {onRetry && (
                        <Button variant="soft" size="2" onClick={onRetry}>
                          Retry
                        </Button>
                      )}
                      {onNewSession && (
                        <Button
                          variant="soft"
                          size="2"
                          color="green"
                          onClick={onNewSession}
                        >
                          New Session
                        </Button>
                      )}
                    </Flex>
                  </Flex>
                ) : hideInput ? null : firstPendingPermission ? (
                  <ComposerSlot compact={compact}>
                    <PermissionSelector
                      toolCall={firstPendingPermission.toolCall}
                      options={firstPendingPermission.options}
                      onSelect={handlePermissionSelect}
                      onCancel={handlePermissionCancel}
                    />
                  </ComposerSlot>
                ) : (
                  <Box className="relative shrink-0">
                    <Box
                      className={`absolute inset-0 flex min-h-[66px] items-center justify-center gap-2 transition-opacity duration-200 ${
                        isRunning
                          ? "pointer-events-none opacity-0"
                          : "opacity-100"
                      }`}
                    >
                      <ConnectingToAgent />
                    </Box>
                    <Box
                      className={`transition-all duration-300 ease-out ${
                        isRunning
                          ? "translate-y-0 opacity-100"
                          : "pointer-events-none translate-y-4 opacity-0"
                      }`}
                    >
                      <ComposerWidth compact={compact}>
                        {taskId && <QueuedMessagesDock taskId={taskId} />}
                        <PromptInput
                          ref={editorRef}
                          sessionId={sessionId}
                          placeholder="Type a message... @ to mention files, ! for bash mode, / for skills"
                          disabled={!isRunning && !handoffInProgress}
                          submitDisabledExternal={
                            handoffInProgress || !isOnline
                          }
                          clearOnSubmit={false}
                          submitTooltipOverride={
                            !isOnline ? "No internet connection" : undefined
                          }
                          isLoading={!!isPromptPending}
                          isActiveSession={isActiveSession}
                          taskId={taskId}
                          repoPath={repoPath}
                          modeOption={modeOption}
                          onModeChange={
                            modeOption ? handleModeChange : undefined
                          }
                          allowBypassPermissions={allowBypassPermissions}
                          enableBashMode={!isCloudRun}
                          modelSelector={
                            <ModelSelector
                              taskId={taskId}
                              disabled={!isRunning}
                            />
                          }
                          reasoningSelector={
                            thoughtOption ? (
                              <ReasoningLevelSelector
                                thoughtOption={thoughtOption}
                                adapter={adapter}
                                onChange={handleThoughtChange}
                                disabled={!isRunning}
                              />
                            ) : null
                          }
                          messagingModeToggle={
                            taskId ? (
                              <SteerQueueToggle taskId={taskId} />
                            ) : undefined
                          }
                          onToggleMessagingMode={toggleMessagingMode}
                          onPromptRecall={handlePromptRecall}
                          onBeforeSubmit={handleBeforeSubmit}
                          onSubmit={handleSubmit}
                          onBashCommand={onBashCommand}
                          onCancel={onCancelPrompt}
                          isEditingQueued={isEditingQueued}
                          onCancelEdit={cancelQueuedEdit}
                        />
                      </ComposerWidth>
                    </Box>
                  </Box>
                )}
              </>
            )}
          </Flex>
        )}
      </ContextMenu.Trigger>
      <ContextMenu.Content size="1">
        <ContextMenu.Item
          onSelect={() => {
            const url = copyTargetUrlRef.current;
            const text = url ?? window.getSelection()?.toString();
            if (!text) {
              return;
            }
            copyFromContextMenu(text, {
              onSuccess: () => toast.success(url ? "Link copied" : "Copied"),
              onError: () => toast.error("Couldn't copy"),
            });
          }}
        >
          Copy
        </ContextMenu.Item>
        <ContextMenu.Separator />
        <ContextMenu.Item onSelect={() => setShowRawLogs(!showRawLogs)}>
          {showRawLogs ? "Back to conversation" : "Show raw logs"}
        </ContextMenu.Item>
      </ContextMenu.Content>
    </ContextMenu.Root>
  );
}
