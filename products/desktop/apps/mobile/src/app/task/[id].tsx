import { Text } from "@components/text";
import { useQueryClient } from "@tanstack/react-query";
import * as Haptics from "expo-haptics";
import { useLocalSearchParams, useRouter } from "expo-router";
import { useCallback, useEffect, useRef, useState } from "react";
import {
  ActivityIndicator,
  Alert,
  Platform,
  Pressable,
  View,
} from "react-native";
import { useReanimatedKeyboardAnimation } from "react-native-keyboard-controller";
import Animated, { useAnimatedStyle } from "react-native-reanimated";
import { FloatingBackButton } from "@/components/FloatingBackButton";
import { usePreferencesStore } from "@/features/preferences/stores/preferencesStore";
import { getTask, runTaskInCloud } from "@/features/tasks/api";
import { CustomImageBadge } from "@/features/tasks/components/CustomImageBadge";
import { FloatingTaskHeader } from "@/features/tasks/components/FloatingTaskHeader";
import { PrDiffStatsBadge } from "@/features/tasks/components/PrDiffStatsBadge";
import { PrStatusBadge } from "@/features/tasks/components/PrStatusBadge";
import { StopRunButton } from "@/features/tasks/components/StopRunButton";
import { TaskSessionView } from "@/features/tasks/components/TaskSessionView";
import { buildCloudPromptBlocks } from "@/features/tasks/composer/attachments/buildCloudPrompt";
import { serializeCloudPrompt } from "@/features/tasks/composer/attachments/cloudPrompt";
import type { PendingAttachment } from "@/features/tasks/composer/attachments/types";
import {
  DEFAULT_EXECUTION_MODE,
  DEFAULT_MODEL,
  DEFAULT_REASONING,
  type ExecutionMode,
  modelSupportsReasoning,
  type ReasoningEffort,
} from "@/features/tasks/composer/options";
import { QueuedMessagesDock } from "@/features/tasks/composer/QueuedMessagesDock";
import { TaskChatComposer } from "@/features/tasks/composer/TaskChatComposer";
import {
  useMessagingMode,
  useQueuedCount,
  useToggleMessagingMode,
} from "@/features/tasks/hooks/useMessagingMode";
import { taskKeys } from "@/features/tasks/hooks/useTasks";
import {
  type MoveDirection,
  type QueuedMessage,
  useMessageQueueStore,
} from "@/features/tasks/stores/messageQueueStore";
import {
  pendingTaskPromptStoreApi,
  usePendingTaskPrompt,
} from "@/features/tasks/stores/pendingTaskPromptStore";
import { useTaskSessionStore } from "@/features/tasks/stores/taskSessionStore";
import { useTaskStore } from "@/features/tasks/stores/taskStore";
import type { Task } from "@/features/tasks/types";
import {
  confirmStopRun,
  isTaskRunning,
} from "@/features/tasks/utils/archiveGuard";
import {
  countUserMessages,
  getSessionActivityPhase,
} from "@/features/tasks/utils/sessionActivity";
import { useScreenInsets } from "@/hooks/useScreenInsets";
import {
  ANALYTICS_EVENTS,
  useActiveTaskAnalyticsContext,
  useAnalytics,
} from "@/lib/analytics";
import { logger } from "@/lib/logger";
import { useThemeColors } from "@/lib/theme";

const log = logger.scope("task-detail");

function getFirstParam(value?: string | string[]): string | undefined {
  return Array.isArray(value) ? value[0] : value;
}

export default function TaskDetailScreen() {
  const {
    id: taskId,
    fromAutomation,
    automationName,
    prompt: initialPrompt,
  } = useLocalSearchParams<{
    id: string;
    fromAutomation?: string;
    automationName?: string;
    prompt?: string;
  }>();
  const router = useRouter();
  const queryClient = useQueryClient();
  const { insets, composerBottom } = useScreenInsets();
  // Pre-compute outside the worklet: useAnimatedStyle runs on the UI thread and
  // can't call the non-worklet getter. Capturing the primitive keeps the worklet
  // closure stable (matches the pattern in task/index.tsx).
  const composerBottomValue = composerBottom();
  const themeColors = useThemeColors();
  const [task, setTask] = useState<Task | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [retrying, setRetrying] = useState(false);

  const {
    connectToTask,
    disconnectFromTask,
    sendPrompt,
    cancelPrompt,
    sendInterrupting,
    sendPermissionResponse,
    setConfigOption,
    getSessionForTask,
    setFocusedTaskId,
    steerQueuedMessage,
    flushQueuedMessagesIfIdle,
    stopRun,
  } = useTaskSessionStore();

  useEffect(() => {
    if (!taskId) return;
    setFocusedTaskId(taskId);
    return () => {
      setFocusedTaskId(null);
    };
  }, [taskId, setFocusedTaskId]);

  // Tag every PostHog event fired while this task is open with the originating
  // inbox report id, so a discuss-launched run can be filtered down in PostHog.
  // Cleared when the screen unmounts. Matches the desktop super-property.
  useActiveTaskAnalyticsContext(task?.signal_report ?? null);

  const session = taskId ? getSessionForTask(taskId) : undefined;

  // Optimistic echo set by the new-task screen (or the terminal-resume path
  // below) so the user's prompt appears in the thread immediately, before
  // the live session catches up.
  const optimisticPrompt = usePendingTaskPrompt(taskId);

  // Clear the echo once the canonical user_message_chunk with matching text
  // arrives via SSE — `TaskSessionView` also dedups visually, but clearing
  // the store frees it for the next submit. Only events with `ts >= setAt`
  // qualify so a text-identical historical turn (e.g. resubmitting
  // "Continue") doesn't drop the echo before the real copy lands.
  useEffect(() => {
    if (!taskId || !optimisticPrompt) return;
    const matched = session?.events.some(
      (e) =>
        e.type === "session_update" &&
        e.notification?.update?.sessionUpdate === "user_message_chunk" &&
        e.notification.update.content?.text === optimisticPrompt.promptText &&
        (e.ts ?? 0) >= optimisticPrompt.setAt,
    );
    if (matched) {
      pendingTaskPromptStoreApi.clear(taskId);
    }
  }, [taskId, optimisticPrompt, session?.events]);

  // Per-task composer pill values. Persisted in taskStore so reopening the
  // task keeps the user's choices; defaults fall back to the same constants
  // the new-task composer uses.
  const composerConfig = useTaskStore((s) =>
    taskId ? s.composerConfigByTaskId[taskId] : undefined,
  );
  const pendingPrompt = useTaskStore((s) =>
    taskId ? s.pendingPromptByTaskId[taskId] : undefined,
  );
  const setComposerConfig = useTaskStore((s) => s.setComposerConfig);
  const setPendingPrompt = useTaskStore((s) => s.setPendingPrompt);
  const consumePendingPrompt = useTaskStore((s) => s.consumePendingPrompt);
  const [initialComposerMessage, setInitialComposerMessage] = useState<
    string | undefined
  >();
  const composerMode: ExecutionMode =
    composerConfig?.mode ?? DEFAULT_EXECUTION_MODE;
  const composerModel = composerConfig?.model ?? DEFAULT_MODEL;
  const composerReasoning: ReasoningEffort =
    composerConfig?.reasoning ?? DEFAULT_REASONING;

  const messagingMode = useMessagingMode(taskId);
  const queuedCount = useQueuedCount(taskId);
  const editingQueuedId = useMessageQueueStore((s) =>
    taskId ? s.editingByTaskId[taskId] : undefined,
  );
  const toggleMessagingMode = useToggleMessagingMode(taskId);
  const analytics = useAnalytics();

  const { height } = useReanimatedKeyboardAnimation();

  // useReanimatedKeyboardAnimation returns negative height values
  // e.g., -300 when keyboard is open, 0 when closed
  const contentPosition = useAnimatedStyle(() => {
    return {
      transform: [{ translateY: height.value }],
    };
  }, []);

  const inputContainerStyle = useAnimatedStyle(() => {
    // contentPosition already translates the whole content up by the keyboard
    // height, so the composer sits at the keyboard top — no extra gap needed
    // when open. Closed state keeps a comfortable bottom inset.
    return {
      marginBottom: height.value < 0 ? 0 : composerBottomValue,
    };
  }, [composerBottomValue]);

  useEffect(() => {
    if (!taskId) return;
    const prompt = getFirstParam(initialPrompt)?.trim();
    if (prompt) setPendingPrompt(taskId, prompt);
  }, [taskId, initialPrompt, setPendingPrompt]);

  useEffect(() => {
    if (!taskId || !pendingPrompt) return;
    const prompt = consumePendingPrompt(taskId);
    if (prompt) setInitialComposerMessage(prompt);
  }, [taskId, pendingPrompt, consumePendingPrompt]);

  useEffect(() => {
    if (!taskId) return;

    let cancelled = false;
    setLoading(true);
    setError(null);

    getTask(taskId)
      .then((fetchedTask) => {
        if (cancelled) return;
        setTask(fetchedTask);
        return connectToTask(fetchedTask);
      })
      .catch((err) => {
        if (cancelled) return;
        log.error("Failed to load task", err);
        setError("Failed to load task");
      })
      .finally(() => {
        if (cancelled) return;
        setLoading(false);
      });

    return () => {
      cancelled = true;
      disconnectFromTask(taskId);
    };
  }, [taskId, connectToTask, disconnectFromTask]);

  // Auto-reconnect if the session disappears while the screen is active
  // (e.g., cloud sandbox expired and the session was cleaned up).
  // Re-fetches the task to get a fresh S3 presigned URL.
  useEffect(() => {
    if (!taskId || !task || loading) return;
    if (session) return;
    if (retrying) return;

    let cancelled = false;
    getTask(taskId)
      .then((freshTask) => {
        if (cancelled) return;
        setTask(freshTask);
        return connectToTask(freshTask);
      })
      .catch((err) => {
        if (cancelled) return;
        log.error("Failed to reconnect to task", err);
      });

    return () => {
      cancelled = true;
    };
  }, [taskId, task, loading, session, connectToTask, retrying]);

  const updateTaskInCache = useCallback(
    (updated: Task) => {
      // Directly patch the task in all list query caches so the task list
      // reflects the change immediately (e.g., environment: local → cloud).
      queryClient.setQueriesData<Task[]>(
        { queryKey: taskKeys.lists() },
        (old) => old?.map((t) => (t.id === updated.id ? updated : t)),
      );
    },
    [queryClient],
  );

  // Resume a terminal (completed/failed) run with a new user prompt. Mirrors
  // the desktop "send on a finished task continues the conversation" UX —
  // creates a fresh run that resumes from the previous one and queues the
  // message as pending_user_message.
  const handleSendAfterTerminal = useCallback(
    async (text: string, attachments: PendingAttachment[]) => {
      if (!taskId || !task) return;
      // Optimistically echo into the chat before tearing down the old session
      // and waiting for the resume run's SSE stream to come up.
      const echoAttachments = attachments.map((a) => ({
        kind: a.kind,
        uri: a.uri,
        fileName: a.fileName,
        mimeType: a.mimeType,
      }));
      pendingTaskPromptStoreApi.set(taskId, {
        promptText: text,
        attachments: echoAttachments.length > 0 ? echoAttachments : undefined,
        setAt: Date.now(),
      });
      try {
        setRetrying(true);
        disconnectFromTask(taskId);

        const pendingUserMessage =
          attachments.length > 0
            ? serializeCloudPrompt(
                await buildCloudPromptBlocks(text, attachments),
              )
            : text;

        const supportsReasoning = modelSupportsReasoning(composerModel);
        const updatedTask = await runTaskInCloud(taskId, {
          resumeFromRunId: task.latest_run?.id,
          pendingUserMessage,
          runtimeAdapter: "claude",
          model: composerModel,
          reasoningEffort: supportsReasoning ? composerReasoning : undefined,
          initialPermissionMode: composerMode,
          rtkEnabled: usePreferencesStore.getState().rtkEnabledCloud,
        });
        setTask(updatedTask);
        await connectToTask(updatedTask);
        updateTaskInCache(updatedTask);
      } catch (err) {
        log.error("Failed to send after terminal", err);
        pendingTaskPromptStoreApi.clear(taskId);
        setRetrying(false);
        Alert.alert(
          "Failed to send",
          "Could not continue this task. Please try again.",
        );
      }
    },
    [
      taskId,
      task,
      disconnectFromTask,
      connectToTask,
      updateTaskInCache,
      composerMode,
      composerModel,
      composerReasoning,
    ],
  );

  const trackPromptSent = useCallback(
    (text: string, isSteer: boolean) => {
      if (!taskId) return;
      analytics.track(ANALYTICS_EVENTS.PROMPT_SENT, {
        task_id: taskId,
        is_initial: false,
        execution_type: "cloud",
        prompt_length_chars: text.length,
        is_steer: isSteer,
      });
    },
    [taskId, analytics],
  );

  const handleSendPrompt = useCallback(
    (text: string, attachments: PendingAttachment[]) => {
      if (!taskId) return;
      Haptics.impactAsync(Haptics.ImpactFeedbackStyle.Light);

      // Saving an in-place edit: overwrite the queued message and release the
      // drain hold. If the turn already ended while editing, flush now — the
      // turn-end drain won't fire again on its own.
      const queue = useMessageQueueStore.getState();
      const editingId = queue.editingByTaskId[taskId];
      if (editingId) {
        queue.update(taskId, editingId, { content: text, attachments });
        queue.clearEditing(taskId);
        flushQueuedMessagesIfIdle(taskId);
        return;
      }

      if (session?.terminalStatus) {
        handleSendAfterTerminal(text, attachments);
        return;
      }

      const onSendFailed = (err: unknown) => {
        log.error("Failed to send prompt", err);
        Alert.alert(
          "Failed to send",
          "Your message could not be delivered. Please try again.",
        );
      };

      // A turn is running. Queue holds the message locally until it ends;
      // Steer interrupts the turn and resends right away.
      if (session?.isPromptPending) {
        if (messagingMode === "queue") {
          useMessageQueueStore.getState().enqueue(taskId, text, attachments);
          return;
        }
        sendInterrupting(taskId, text, attachments)
          .then(() => trackPromptSent(text, true))
          .catch(onSendFailed);
        return;
      }

      sendPrompt(taskId, text, attachments)
        .then(() => trackPromptSent(text, false))
        .catch(onSendFailed);
    },
    [
      taskId,
      sendPrompt,
      sendInterrupting,
      session?.terminalStatus,
      session?.isPromptPending,
      messagingMode,
      handleSendAfterTerminal,
      trackPromptSent,
      flushQueuedMessagesIfIdle,
    ],
  );

  const [restoredDraft, setRestoredDraft] = useState<{
    text: string;
    attachments: PendingAttachment[];
  }>();

  const handleSteerQueued = useCallback(
    (message: QueuedMessage) => {
      if (!taskId) return;
      steerQueuedMessage(taskId, message.id)
        .then(() => trackPromptSent(message.content, true))
        .catch((err) => {
          log.error("Failed to steer queued message", err);
          Alert.alert(
            "Couldn't steer",
            "This message is still queued. Please try again.",
          );
        });
    },
    [taskId, steerQueuedMessage, trackPromptSent],
  );

  // Pull a queued message into the composer for an in-place edit. It stays in
  // the queue at its position (marked as the edit target); the next send saves
  // it back rather than sending a new prompt.
  const handleEditQueued = useCallback(
    (message: QueuedMessage) => {
      if (!taskId) return;
      useMessageQueueStore.getState().setEditing(taskId, message.id);
      setRestoredDraft({
        text: message.content,
        attachments: message.attachments,
      });
    },
    [taskId],
  );

  const handleCancelEdit = useCallback(() => {
    if (!taskId) return;
    useMessageQueueStore.getState().clearEditing(taskId);
    setRestoredDraft({ text: "", attachments: [] });
    flushQueuedMessagesIfIdle(taskId);
  }, [taskId, flushQueuedMessagesIfIdle]);

  const handleMoveQueued = useCallback(
    (message: QueuedMessage, direction: MoveDirection) => {
      if (!taskId) return;
      Haptics.selectionAsync();
      useMessageQueueStore.getState().move(taskId, message.id, direction);
    },
    [taskId],
  );

  const handleDiscardQueued = useCallback(
    (message: QueuedMessage) => {
      if (!taskId) return;
      const wasEditing =
        useMessageQueueStore.getState().editingByTaskId[taskId] === message.id;
      useMessageQueueStore.getState().remove(taskId, message.id);
      if (wasEditing) setRestoredDraft({ text: "", attachments: [] });
    },
    [taskId],
  );

  const handleModeChange = useCallback(
    (value: ExecutionMode) => {
      if (!taskId) return;
      setComposerConfig(taskId, { mode: value });
      // Push to the live cloud session so the next turn uses the new mode.
      // Silently ignore failures — value is already persisted locally and
      // will be replayed if the user resumes from a terminal state.
      setConfigOption(taskId, "mode", value).catch(() => {});
    },
    [taskId, setComposerConfig, setConfigOption],
  );

  const handleModelChange = useCallback(
    (value: string) => {
      if (!taskId) return;
      setComposerConfig(taskId, { model: value });
      setConfigOption(taskId, "model", value).catch(() => {});
    },
    [taskId, setComposerConfig, setConfigOption],
  );

  const handleReasoningChange = useCallback(
    (value: ReasoningEffort) => {
      if (!taskId) return;
      setComposerConfig(taskId, { reasoning: value });
      setConfigOption(taskId, "effort", value).catch(() => {});
      usePreferencesStore.getState().setLastUsedReasoningEffort(value);
    },
    [taskId, setComposerConfig, setConfigOption],
  );

  const handleStop = useCallback(() => {
    if (!taskId) return;
    // cancelPrompt returns false on failure — no need to alert,
    // the agent may have already finished or the sandbox expired.
    cancelPrompt(taskId).catch(() => {});
  }, [taskId, cancelPrompt]);

  const handleStopRun = useCallback(() => {
    if (!taskId) return;
    confirmStopRun(() => {
      const promptsSent = countUserMessages(getSessionForTask(taskId)?.events);
      stopRun(taskId)
        .then((ok) => {
          if (ok) {
            analytics.track(ANALYTICS_EVENTS.TASK_RUN_STOPPED, {
              task_id: taskId,
              execution_type: "cloud",
              prompts_sent: promptsSent,
            });
          } else {
            Alert.alert(
              "Couldn't stop",
              "The run could not be stopped. Please try again.",
            );
          }
        })
        .catch(() => {});
    });
  }, [taskId, stopRun, analytics, getSessionForTask]);

  const canStopRun =
    !!task &&
    !!session &&
    !session.terminalStatus &&
    !session.stopRequested &&
    task.latest_run?.environment !== "local" &&
    isTaskRunning(task);

  const handleRetry = useCallback(async () => {
    if (!taskId || !task) return;
    try {
      setRetrying(true);
      disconnectFromTask(taskId);

      const updatedTask = await runTaskInCloud(taskId, {
        resumeFromRunId: task.latest_run?.id,
        rtkEnabled: usePreferencesStore.getState().rtkEnabledCloud,
      });
      setTask(updatedTask);
      await connectToTask(updatedTask);
      updateTaskInCache(updatedTask);
      // Don't clear retrying here — the effect below clears it
      // once the session shows meaningful state (thinking or terminal).
    } catch (err) {
      log.error("Failed to retry task", err);
      setRetrying(false);
      Alert.alert(
        "Retry failed",
        "Could not restart the task. Please try again.",
      );
    }
  }, [taskId, task, disconnectFromTask, connectToTask, updateTaskInCache]);

  // Clear retrying once the agent finishes a turn or the run terminates.
  useEffect(() => {
    if (!retrying || !session) return;
    if (!session.isPromptPending || session.terminalStatus) {
      setRetrying(false);
    }
  }, [retrying, session]);

  const handleSendPermissionResponse = useCallback(
    (args: Parameters<typeof sendPermissionResponse>[1]) => {
      if (!taskId) return;
      sendPermissionResponse(taskId, args).catch((err) => {
        log.error("Failed to send permission response", err);
        Alert.alert(
          "Failed to respond",
          "Your permission response could not be sent. Please try again.",
        );
      });
    },
    [taskId, sendPermissionResponse],
  );

  const handleOpenTask = useCallback(
    (newTaskId: string) => {
      router.replace(`/task/${newTaskId}`);
    },
    [router],
  );

  const prUrl = task?.latest_run?.output?.pr_url as string | undefined;

  const activityPhase = getSessionActivityPhase({ retrying, session });
  const isConnecting = activityPhase === "connecting";
  const isThinking = activityPhase === "working";

  // Show the loading overlay until the SSE snapshot has populated the
  // session's events. For tasks that already have a run (i.e. opening an
  // old task), `session.status` stays `"connecting"` until the first
  // snapshot arrives — that's when historical events become available.
  // For brand-new tasks (no `latest_run`), there's no history to wait
  // for, so we only gate on the initial metadata fetch.
  const isHistoryLoading =
    !!task?.latest_run &&
    !!session &&
    session.status === "connecting" &&
    session.events.length === 0;
  // Suppress the full-screen overlay when we have an optimistic prompt to
  // show — the user just submitted and seeing their own text + a connecting
  // indicator is friendlier than a blank spinner.
  const showLoading = (loading || isHistoryLoading) && !optimisticPrompt;
  const showAutomationContext =
    fromAutomation === "1" || task?.origin_product === "automation";
  const automationContextLabel =
    automationName ??
    (task?.origin_product === "automation"
      ? "This run was started from a task automation."
      : null);

  // Haptic pulse when connecting/thinking indicators dismiss
  const prevWaiting = useRef(false);
  useEffect(() => {
    const waiting = isConnecting || isThinking;
    if (prevWaiting.current && !waiting) {
      Haptics.impactAsync(Haptics.ImpactFeedbackStyle.Light);
    }
    prevWaiting.current = waiting;
  }, [isConnecting, isThinking]);

  if (error || (!task && !loading)) {
    return (
      <View className="flex-1 items-center justify-center bg-background px-4">
        <FloatingBackButton />
        <Text className="mb-4 text-center text-status-error">
          {error || "Task not found"}
        </Text>
        <Pressable
          onPress={() => router.back()}
          className="rounded-lg bg-gray-3 px-4 py-2"
        >
          <Text className="text-gray-12">Go back</Text>
        </Pressable>
      </View>
    );
  }

  return (
    <View className="flex-1 bg-background">
      <FloatingTaskHeader
        title={showLoading ? "Loading..." : task?.title || "Task"}
        subtitle={task?.repository ?? undefined}
        rightSlot={
          <>
            {task ? <CustomImageBadge task={task} /> : null}
            {canStopRun ? (
              <StopRunButton onPress={handleStopRun} />
            ) : prUrl ? (
              <>
                <PrDiffStatsBadge prUrl={prUrl} />
                <PrStatusBadge prUrl={prUrl} />
              </>
            ) : null}
          </>
        }
      />
      <Animated.View className="flex-1" style={contentPosition}>
        {showAutomationContext && automationContextLabel && (
          <View
            className="absolute inset-x-3 z-10 rounded-lg border border-accent-6 bg-accent-2 px-3 py-2"
            style={{ top: (Platform.OS === "ios" ? 6 : insets.top) + 52 }}
          >
            <Text className="text-accent-11 text-xs">
              {automationName
                ? `Started from automation: ${automationName}`
                : automationContextLabel}
            </Text>
          </View>
        )}

        {/* Always render TaskSessionView so the FlatList can layout behind
            the loading overlay. This prevents the "flash of messages" when
            switching from loading spinner to rendered content. The FlatList
            takes the available space above the composer (flex-1), so we
            don't need to reserve composer height as paddingTop — only the
            top header's space (paddingBottom in an inverted list) plus a
            small visual buffer at the bottom. */}
        <TaskSessionView
          events={session?.events ?? []}
          taskId={taskId}
          pendingPermissions={session?.pendingPermissions}
          isConnecting={isConnecting}
          isThinking={isThinking}
          terminalStatus={retrying ? undefined : session?.terminalStatus}
          lastError={retrying ? undefined : session?.lastError}
          onRetry={
            !retrying && session?.terminalStatus ? handleRetry : undefined
          }
          onOpenTask={handleOpenTask}
          onSendPermissionResponse={handleSendPermissionResponse}
          optimisticUserMessage={
            optimisticPrompt
              ? {
                  text: optimisticPrompt.promptText,
                  attachments: optimisticPrompt.attachments,
                  setAt: optimisticPrompt.setAt,
                }
              : undefined
          }
          contentContainerStyle={{
            paddingTop: 8,
            paddingBottom:
              (Platform.OS === "ios" ? 6 : insets.top) +
              60 +
              (showAutomationContext ? 44 : 0),
          }}
        />

        {/* Loading overlay — covers the list while initial task metadata
            is fetched AND while the SSE watcher is still loading the
            historical events snapshot for an existing run. */}
        {showLoading && (
          <View className="absolute inset-0 items-center justify-center bg-background">
            <ActivityIndicator size="large" color={themeColors.accent[9]} />
            <Text className="mt-4 text-gray-11">
              {task?.latest_run
                ? loading
                  ? "Connecting..."
                  : "Loading history..."
                : "Loading task..."}
            </Text>
          </View>
        )}

        {/* Composer below the list in flex flow — its real height
            determines how much vertical space the list above gets, so the
            last message can never sit behind the input. Stays visible on
            terminal runs so the user can send a follow-up that resumes. */}
        <Animated.View style={inputContainerStyle}>
          {taskId ? (
            <QueuedMessagesDock
              taskId={taskId}
              canSteer={
                !!session?.isPromptPending &&
                !session?.isCompacting &&
                !session?.terminalStatus
              }
              onSteer={handleSteerQueued}
              onEdit={handleEditQueued}
              onDiscard={handleDiscardQueued}
              onMove={handleMoveQueued}
            />
          ) : null}
          <TaskChatComposer
            onSend={handleSendPrompt}
            restoredDraft={restoredDraft}
            editing={!!editingQueuedId}
            onCancelEdit={handleCancelEdit}
            onStop={handleStop}
            isUserTurn={!(session?.isPromptPending ?? true)}
            placeholder={
              session?.terminalStatus ? "Resume this task..." : "Ask a question"
            }
            initialMessage={initialComposerMessage}
            mode={composerMode}
            model={composerModel}
            reasoning={composerReasoning}
            onModeChange={handleModeChange}
            onModelChange={handleModelChange}
            onReasoningChange={handleReasoningChange}
            messagingMode={messagingMode}
            queuedCount={queuedCount}
            onToggleMessagingMode={toggleMessagingMode}
          />
        </Animated.View>
      </Animated.View>
    </View>
  );
}
