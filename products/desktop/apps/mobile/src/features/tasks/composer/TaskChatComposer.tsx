import { Text } from "@components/text";
import { DEFAULT_CLAUDE_EXECUTION_MODE } from "@posthog/core/sessions/executionModes";
import type { CloudComposerSelection } from "@posthog/core/task-detail/composerModelPolicy";
import { resolveCloudComposerModelChange } from "@posthog/core/task-detail/composerModelPolicy";
import {
  type Adapter,
  DEFAULT_GATEWAY_MODEL,
  DEFAULT_REASONING_EFFORT,
  type ExecutionMode,
  KIMI_MODEL_FLAG,
  type SupportedReasoningEffort,
} from "@posthog/shared";
import * as Haptics from "expo-haptics";
import {
  ArrowUp,
  Lightning,
  Microphone,
  PaperclipIcon,
  PencilIcon,
  Stack,
  Stop,
} from "phosphor-react-native";
import { useFeatureFlag } from "posthog-react-native";
import type { ReactNode } from "react";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  ActivityIndicator,
  Alert,
  Keyboard,
  Pressable,
  ScrollView,
  TextInput,
  View,
} from "react-native";
import { useVoiceRecording } from "@/features/chat";
import { useCloudTaskConfigOptions } from "@/features/tasks/hooks/useCloudTaskConfigOptions";
import { logger } from "@/lib/logger";
import { useThemeColors } from "@/lib/theme";
import type { MessagingMode } from "../stores/messagingModeStore";
import { AgentConfigControls } from "./AgentConfigControls";
import { AttachmentSheet } from "./attachments/AttachmentSheet";
import {
  type AttachmentStatus,
  AttachmentsBar,
} from "./attachments/AttachmentsBar";
import { attachmentPreparer } from "./attachments/buildCloudPrompt";
import {
  captureFromCamera,
  pickDocument,
  pickPhotoFromLibrary,
} from "./attachments/pickers";
import type { PendingAttachment } from "./attachments/types";
import {
  type ContextWindow,
  filterKimiModelConfigOptions,
  getModelConfigOption,
  resolveComposerPrimaryAction,
} from "./options";
import { Pill } from "./Pill";
import {
  type ComposerContent,
  isComposerEmpty,
  submitComposerMessage,
} from "./submitComposerMessage";

const log = logger.scope("task-chat-composer");
interface TaskChatComposerProps {
  onSend: (
    message: string,
    attachments: PendingAttachment[],
  ) => Promise<boolean>;
  onStop?: () => void;
  disabled?: boolean;
  placeholder?: string;
  initialMessage?: string;
  isUserTurn?: boolean;
  /** Current pill values (persisted per-task by the caller). */
  adapter: Adapter;
  mode: ExecutionMode;
  model: string;
  reasoning: SupportedReasoningEffort;
  contextWindow: ContextWindow;
  fastMode: boolean;
  onAdapterChange: (selection: CloudComposerSelection) => void;
  canChangeAdapter?: boolean;
  onModeChange: (mode: ExecutionMode) => void;
  onModelChange: (model: string) => void;
  onReasoningChange: (reasoning: SupportedReasoningEffort) => void;
  onContextWindowChange: (contextWindow: ContextWindow) => void;
  onFastModeChange: (enabled: boolean) => void;
  /** Steer vs Queue behaviour for messages sent while a turn is running. */
  messagingMode: MessagingMode;
  queuedCount: number;
  onToggleMessagingMode: () => void;
  /** A queued message pulled back for editing; pass a fresh object to restore. */
  restoredDraft?: { text: string; attachments: PendingAttachment[] };
  /** True while editing a queued message in place; the next send saves it. */
  editing?: boolean;
  onCancelEdit?: () => void;
  /** Run artifacts trigger, rendered in the composer toolbar row. */
  artifactsSlot?: ReactNode;
}

export function TaskChatComposer({
  onSend,
  onStop,
  disabled = false,
  placeholder = "Ask a question",
  initialMessage,
  isUserTurn = false,
  adapter,
  mode,
  model,
  reasoning,
  contextWindow,
  fastMode,
  onAdapterChange,
  canChangeAdapter = true,
  onModeChange,
  onModelChange,
  onReasoningChange,
  onContextWindowChange,
  onFastModeChange,
  messagingMode,
  queuedCount,
  onToggleMessagingMode,
  restoredDraft,
  editing = false,
  onCancelEdit,
  artifactsSlot,
}: TaskChatComposerProps) {
  const themeColors = useThemeColors();
  const { configOptions: liveConfigOptions, hasLiveConfig } =
    useCloudTaskConfigOptions(adapter);
  const kimiEnabled = !!useFeatureFlag(KIMI_MODEL_FLAG);
  const configOptions = useMemo(
    () => filterKimiModelConfigOptions(liveConfigOptions, kimiEnabled),
    [liveConfigOptions, kimiEnabled],
  );
  const modelConfigOption = getModelConfigOption(configOptions);
  const [message, setMessage] = useState(() => initialMessage ?? "");
  const [attachments, setAttachments] = useState<PendingAttachment[]>([]);
  const [attachmentStatus, setAttachmentStatus] = useState<
    Record<string, AttachmentStatus>
  >({});
  const [attachmentSheetOpen, setAttachmentSheetOpen] = useState(false);

  // Mirror composer state into refs so a failed send can read the current
  // value after awaiting, rather than the value captured when it was sent.
  const messageRef = useRef(message);
  messageRef.current = message;
  const attachmentsRef = useRef(attachments);
  attachmentsRef.current = attachments;
  const submissionRef = useRef(0);

  const clearStatus = useCallback((id: string) => {
    setAttachmentStatus((prev) => {
      if (!(id in prev)) return prev;
      const { [id]: _dropped, ...rest } = prev;
      return rest;
    });
  }, []);

  // Encode eagerly so oversized/unsupported files fail at attach, not send.
  const beginPreparing = useCallback(
    (att: PendingAttachment) => {
      setAttachmentStatus((prev) => ({ ...prev, [att.id]: "preparing" }));
      attachmentPreparer.prepare(att).then(
        () => {
          if (attachmentsRef.current.some((a) => a.id === att.id)) {
            clearStatus(att.id);
          }
        },
        (error: unknown) => {
          if (!attachmentsRef.current.some((a) => a.id === att.id)) return;
          setAttachmentStatus((prev) => ({ ...prev, [att.id]: "error" }));
          Alert.alert(
            "Attachment can't be sent",
            error instanceof Error
              ? error.message
              : "This file couldn't be prepared. Remove it and try another.",
          );
        },
      );
    },
    [clearStatus],
  );

  const loadAttachments = useCallback(
    (next: PendingAttachment[]) => {
      setAttachments(next);
      setAttachmentStatus({});
      for (const att of next) beginPreparing(att);
    },
    [beginPreparing],
  );

  useEffect(() => {
    if (!initialMessage) return;
    setMessage(initialMessage);
  }, [initialMessage]);

  useEffect(() => {
    if (!restoredDraft) return;
    setMessage(restoredDraft.text);
    loadAttachments(restoredDraft.attachments);
  }, [restoredDraft, loadAttachments]);

  useEffect(
    () => () => {
      for (const att of attachmentsRef.current) {
        attachmentPreparer.forget(att.id);
      }
    },
    [],
  );

  useEffect(() => {
    if (!hasLiveConfig) return;
    const next = resolveCloudComposerModelChange({
      adapter,
      modelOption: modelConfigOption,
      requestedModel: model,
      reasoning,
    });
    if (next.model !== model) onModelChange(next.model);
    if (next.reasoning !== reasoning) onReasoningChange(next.reasoning);
  }, [
    adapter,
    hasLiveConfig,
    model,
    modelConfigOption,
    onModelChange,
    onReasoningChange,
    reasoning,
  ]);

  const appendTranscript = useCallback((transcript: string) => {
    setMessage((prev) => (prev ? `${prev} ${transcript}` : transcript));
  }, []);

  const { status, startRecording, stopRecording, cancelRecording } =
    useVoiceRecording({ onTranscript: appendTranscript });

  const isRecording = status === "recording";
  const isTranscribing = status === "transcribing";

  const hasContent = !isComposerEmpty({ text: message, attachments });
  const statuses = Object.values(attachmentStatus);
  const attachmentsPreparing = statuses.includes("preparing");
  const sendBlocked = attachmentsPreparing || statuses.includes("error");
  const primaryAction = resolveComposerPrimaryAction({
    hasContent,
    disabled: disabled || sendBlocked,
    isRecording,
    isTranscribing,
    canStop: !isUserTurn && !!onStop,
    allowSendWhileRunning: true,
  });
  const canSend = primaryAction === "send";
  const showStop = primaryAction === "stop";

  const applyContent = (content: ComposerContent) => {
    setMessage(content.text);
    loadAttachments(content.attachments);
  };

  const handleSend = () => {
    if (!hasContent || disabled) return;
    const submitted: ComposerContent = { text: message.trim(), attachments };
    const submissionId = ++submissionRef.current;
    Keyboard.dismiss();
    void submitComposerMessage({
      submitted,
      clear: () => applyContent({ text: "", attachments: [] }),
      send: () => onSend(submitted.text, submitted.attachments),
      isLatestSubmission: () => submissionId === submissionRef.current,
      isEmpty: () =>
        isComposerEmpty({
          text: messageRef.current,
          attachments: attachmentsRef.current,
        }),
      restore: applyContent,
    });
  };

  const addAttachment = async (
    picker: () => Promise<PendingAttachment | null>,
  ) => {
    try {
      const att = await picker();
      if (att) {
        setAttachments((prev) => [...prev, att]);
        beginPreparing(att);
      }
    } catch (err) {
      log.error("Failed to pick attachment", err);
    }
  };

  const removeAttachment = (id: string) => {
    setAttachments((prev) => prev.filter((a) => a.id !== id));
    attachmentPreparer.forget(id);
    clearStatus(id);
  };

  const handleMicPress = async () => {
    if (isRecording) {
      await stopRecording();
    } else if (!isTranscribing) {
      await startRecording();
    }
  };

  const handleMicLongPress = async () => {
    if (isRecording) {
      await cancelRecording();
    }
  };

  const handleStop = () => {
    Haptics.impactAsync(Haptics.ImpactFeedbackStyle.Medium);
    onStop?.();
  };

  const isSteer = messagingMode === "steer";
  const messagingModeLabel = isSteer
    ? "Steer"
    : queuedCount > 0
      ? `Queue (${queuedCount})`
      : "Queue";

  const handleToggleMessagingMode = () => {
    Haptics.selectionAsync();
    onToggleMessagingMode();
  };

  return (
    <>
      <View className="px-4">
        <View style={{ width: "100%", maxWidth: 600, alignSelf: "center" }}>
          <View className="overflow-hidden rounded-lg border border-gray-6 bg-card">
            {editing ? (
              <View className="flex-row items-center gap-2 border-gray-6 border-b bg-accent-2 px-3 py-2">
                <PencilIcon size={14} color={themeColors.accent[11]} />
                <Text className="flex-1 text-[12px] text-accent-11">
                  Editing queued message
                </Text>
                <Pressable
                  hitSlop={8}
                  onPress={onCancelEdit}
                  accessibilityRole="button"
                  accessibilityLabel="Cancel editing"
                  className="active:opacity-60"
                >
                  <Text className="font-medium text-[12px] text-gray-11">
                    Cancel
                  </Text>
                </Pressable>
              </View>
            ) : null}
            <AttachmentsBar
              attachments={attachments}
              onRemove={removeAttachment}
              statuses={attachmentStatus}
            />
            <TextInput
              className="px-4 pt-3.5 pb-3 text-[15px] text-gray-12"
              style={{ minHeight: 64, maxHeight: 200 }}
              placeholder={
                isRecording
                  ? "Recording..."
                  : isTranscribing
                    ? "Transcribing..."
                    : placeholder
              }
              placeholderTextColor={themeColors.gray[9]}
              value={message}
              onChangeText={setMessage}
              editable={!disabled && !isRecording}
              multiline
              textAlignVertical="top"
            />

            <View className="flex-row items-center gap-2 px-2 pb-2">
              <Pressable
                hitSlop={8}
                onPress={() => setAttachmentSheetOpen(true)}
                disabled={disabled || isRecording}
                accessibilityLabel="Add attachment"
                accessibilityRole="button"
                className="h-9 w-9 items-center justify-center active:opacity-60"
              >
                <PaperclipIcon
                  size={18}
                  color={
                    attachments.length > 0
                      ? themeColors.accent[11]
                      : themeColors.gray[10]
                  }
                  weight={attachments.length > 0 ? "fill" : "regular"}
                />
              </Pressable>

              {artifactsSlot}

              <ScrollView
                horizontal
                showsHorizontalScrollIndicator={false}
                keyboardShouldPersistTaps="handled"
                className="flex-1"
                contentContainerStyle={{
                  alignItems: "center",
                  gap: 6,
                  paddingRight: 4,
                }}
              >
                <AgentConfigControls
                  adapter={adapter}
                  mode={mode}
                  model={model}
                  reasoning={reasoning}
                  contextWindow={contextWindow}
                  fastMode={fastMode}
                  configOptions={configOptions}
                  onAdapterChange={onAdapterChange}
                  onModeChange={onModeChange}
                  onModelChange={onModelChange}
                  onReasoningChange={onReasoningChange}
                  onContextWindowChange={onContextWindowChange}
                  onFastModeChange={onFastModeChange}
                  canChangeAdapter={canChangeAdapter}
                />

                <Pill
                  icon={
                    isSteer ? (
                      <Lightning
                        size={14}
                        color={themeColors.accent[11]}
                        weight="fill"
                      />
                    ) : (
                      <Stack size={14} color={themeColors.gray[11]} />
                    )
                  }
                  label={messagingModeLabel}
                  accent={isSteer}
                  onPress={handleToggleMessagingMode}
                />
              </ScrollView>

              <Pressable
                onPress={
                  canSend ? handleSend : showStop ? handleStop : handleMicPress
                }
                onLongPress={handleMicLongPress}
                disabled={isTranscribing || disabled || sendBlocked}
                className={`h-9 w-9 items-center justify-center rounded-lg ${
                  canSend ? "bg-gray-12" : "bg-gray-3"
                }`}
              >
                {isTranscribing || attachmentsPreparing ? (
                  <ActivityIndicator
                    size="small"
                    color={themeColors.gray[12]}
                  />
                ) : canSend || sendBlocked ? (
                  <ArrowUp
                    size={18}
                    color={
                      canSend ? themeColors.background : themeColors.gray[9]
                    }
                    weight="bold"
                  />
                ) : isRecording || showStop ? (
                  <Stop
                    size={18}
                    color={themeColors.status.error}
                    weight="fill"
                  />
                ) : (
                  <Microphone size={18} color={themeColors.gray[12]} />
                )}
              </Pressable>
            </View>
          </View>
        </View>
      </View>

      <AttachmentSheet
        open={attachmentSheetOpen}
        onClose={() => setAttachmentSheetOpen(false)}
        onPickPhoto={() => addAttachment(pickPhotoFromLibrary)}
        onPickCamera={() => addAttachment(captureFromCamera)}
        onPickDocument={() => addAttachment(pickDocument)}
      />
    </>
  );
}

export const TASK_CHAT_DEFAULTS = {
  mode: DEFAULT_CLAUDE_EXECUTION_MODE,
  model: DEFAULT_GATEWAY_MODEL,
  reasoning: DEFAULT_REASONING_EFFORT,
} as const;
