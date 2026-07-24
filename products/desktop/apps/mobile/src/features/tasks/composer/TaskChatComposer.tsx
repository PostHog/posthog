import { Text } from "@components/text";
import * as Haptics from "expo-haptics";
import {
  ArrowUp,
  BrainIcon,
  Lightning,
  Microphone,
  PaperclipIcon,
  PauseIcon,
  PencilIcon,
  Robot,
  ShieldCheck,
  Sparkle,
  Stack,
  Stop,
} from "phosphor-react-native";
import {
  type ReactNode,
  useCallback,
  useEffect,
  useRef,
  useState,
} from "react";
import {
  ActivityIndicator,
  Animated,
  Easing,
  Keyboard,
  Pressable,
  ScrollView,
  TextInput,
  View,
} from "react-native";
import { useVoiceRecording } from "@/features/chat";
import { logger } from "@/lib/logger";
import { useThemeColors } from "@/lib/theme";
import type { MessagingMode } from "../stores/messagingModeStore";
import { AttachmentSheet } from "./attachments/AttachmentSheet";
import { AttachmentsBar } from "./attachments/AttachmentsBar";
import {
  captureFromCamera,
  pickDocument,
  pickPhotoFromLibrary,
} from "./attachments/pickers";
import type { PendingAttachment } from "./attachments/types";
import {
  DEFAULT_EXECUTION_MODE,
  DEFAULT_MODEL,
  DEFAULT_REASONING,
  EXECUTION_MODES,
  type ExecutionMode,
  MODELS,
  modeLabel,
  modelLabel,
  modelSupportsReasoning,
  REASONING_LEVELS,
  type ReasoningEffort,
  reasoningLabel,
} from "./options";
import { Pill } from "./Pill";
import { SelectSheet } from "./SelectSheet";

const log = logger.scope("task-chat-composer");

interface TaskChatComposerProps {
  onSend: (message: string, attachments: PendingAttachment[]) => void;
  onStop?: () => void;
  disabled?: boolean;
  placeholder?: string;
  initialMessage?: string;
  isUserTurn?: boolean;
  /** Current pill values (persisted per-task by the caller). */
  mode: ExecutionMode;
  model: string;
  reasoning: ReasoningEffort;
  onModeChange: (mode: ExecutionMode) => void;
  onModelChange: (model: string) => void;
  onReasoningChange: (reasoning: ReasoningEffort) => void;
  /** Steer vs Queue behaviour for messages sent while a turn is running. */
  messagingMode: MessagingMode;
  queuedCount: number;
  onToggleMessagingMode: () => void;
  /** A queued message pulled back for editing; pass a fresh object to restore. */
  restoredDraft?: { text: string; attachments: PendingAttachment[] };
  /** True while editing a queued message in place; the next send saves it. */
  editing?: boolean;
  onCancelEdit?: () => void;
}

function modeIcon(mode: ExecutionMode, color: string, size = 14): ReactNode {
  switch (mode) {
    case "plan":
      return <PauseIcon size={size} color={color} weight="bold" />;
    case "default":
      return <PencilIcon size={size} color={color} />;
    case "acceptEdits":
      return <ShieldCheck size={size} color={color} />;
    case "auto":
      return <Sparkle size={size} color={color} weight="fill" />;
  }
}

function PulsingBorder({ active, color }: { active: boolean; color: string }) {
  const opacity = useRef(new Animated.Value(0)).current;
  const animRef = useRef<Animated.CompositeAnimation | null>(null);

  useEffect(() => {
    if (active) {
      opacity.setValue(0);
      animRef.current = Animated.loop(
        Animated.sequence([
          Animated.timing(opacity, {
            toValue: 1,
            duration: 1500,
            easing: Easing.inOut(Easing.ease),
            useNativeDriver: true,
          }),
          Animated.timing(opacity, {
            toValue: 0,
            duration: 1500,
            easing: Easing.inOut(Easing.ease),
            useNativeDriver: true,
          }),
        ]),
      );
      animRef.current.start();
    } else {
      animRef.current?.stop();
      animRef.current = null;
      opacity.setValue(0);
    }
    return () => {
      animRef.current?.stop();
    };
  }, [active, opacity]);

  if (!active) return null;

  return (
    <Animated.View
      pointerEvents="none"
      style={{
        position: "absolute",
        top: 0,
        left: 0,
        right: 0,
        bottom: 0,
        opacity,
        borderWidth: 2,
        borderColor: color,
        borderRadius: 16,
      }}
    />
  );
}

export function TaskChatComposer({
  onSend,
  onStop,
  disabled = false,
  placeholder = "Ask a question",
  initialMessage,
  isUserTurn = false,
  mode,
  model,
  reasoning,
  onModeChange,
  onModelChange,
  onReasoningChange,
  messagingMode,
  queuedCount,
  onToggleMessagingMode,
  restoredDraft,
  editing = false,
  onCancelEdit,
}: TaskChatComposerProps) {
  const themeColors = useThemeColors();
  const [message, setMessage] = useState(() => initialMessage ?? "");
  const [attachments, setAttachments] = useState<PendingAttachment[]>([]);
  const [attachmentSheetOpen, setAttachmentSheetOpen] = useState(false);

  useEffect(() => {
    if (!initialMessage) return;
    setMessage(initialMessage);
  }, [initialMessage]);

  useEffect(() => {
    if (!restoredDraft) return;
    setMessage(restoredDraft.text);
    setAttachments(restoredDraft.attachments);
  }, [restoredDraft]);

  const appendTranscript = useCallback((transcript: string) => {
    setMessage((prev) => (prev ? `${prev} ${transcript}` : transcript));
  }, []);

  const { status, startRecording, stopRecording, cancelRecording } =
    useVoiceRecording({ onTranscript: appendTranscript });

  const isRecording = status === "recording";
  const isTranscribing = status === "transcribing";

  const [modeSheetOpen, setModeSheetOpen] = useState(false);
  const [modelSheetOpen, setModelSheetOpen] = useState(false);
  const [reasoningSheetOpen, setReasoningSheetOpen] = useState(false);

  const showReasoningPill = modelSupportsReasoning(model);

  const hasContent = message.trim().length > 0 || attachments.length > 0;
  const canSend = hasContent && !disabled && !isRecording;
  const showStop =
    !isUserTurn && !canSend && !isRecording && !isTranscribing && !!onStop;

  const handleSend = () => {
    const trimmed = message.trim();
    if (!hasContent || disabled) return;
    setMessage("");
    setAttachments([]);
    Keyboard.dismiss();
    onSend(trimmed, attachments);
  };

  const addAttachment = async (
    picker: () => Promise<PendingAttachment | null>,
  ) => {
    try {
      const att = await picker();
      if (att) setAttachments((prev) => [...prev, att]);
    } catch (err) {
      log.error("Failed to pick attachment", err);
    }
  };

  const removeAttachment = (id: string) => {
    setAttachments((prev) => prev.filter((a) => a.id !== id));
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
      <View className="px-3">
        <View className="relative">
          <PulsingBorder active={isUserTurn} color={themeColors.accent[9]} />
          <View className="overflow-hidden rounded-2xl border border-gray-6 bg-card">
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
            />
            <TextInput
              className="px-4 pt-3.5 pb-3 text-[15px] text-gray-12"
              style={{ minHeight: 56, maxHeight: 200 }}
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

                <Pill
                  icon={modeIcon(
                    mode,
                    mode === "plan"
                      ? themeColors.accent[11]
                      : themeColors.gray[11],
                  )}
                  label={modeLabel(mode)}
                  accent={mode === "plan"}
                  onPress={() => setModeSheetOpen(true)}
                />

                <Pill
                  icon={<Robot size={14} color={themeColors.gray[11]} />}
                  label={modelLabel(model)}
                  onPress={() => setModelSheetOpen(true)}
                />

                {showReasoningPill ? (
                  <Pill
                    icon={<BrainIcon size={14} color={themeColors.gray[11]} />}
                    label={reasoningLabel(reasoning)}
                    onPress={() => setReasoningSheetOpen(true)}
                  />
                ) : null}
              </ScrollView>

              <Pressable
                onPress={
                  canSend ? handleSend : showStop ? handleStop : handleMicPress
                }
                onLongPress={handleMicLongPress}
                disabled={isTranscribing || disabled}
                className={`h-9 w-9 items-center justify-center rounded-lg ${
                  canSend ? "bg-gray-12" : "bg-gray-3"
                }`}
              >
                {isTranscribing ? (
                  <ActivityIndicator
                    size="small"
                    color={themeColors.gray[12]}
                  />
                ) : canSend ? (
                  <ArrowUp
                    size={18}
                    color={themeColors.background}
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

      <SelectSheet
        open={modeSheetOpen}
        title="Execution mode"
        value={mode}
        onChange={(v) => onModeChange(v as ExecutionMode)}
        onClose={() => setModeSheetOpen(false)}
        options={EXECUTION_MODES.map((m) => ({
          value: m.value,
          label: m.label,
          description: m.description,
          icon: modeIcon(
            m.value,
            m.value === "plan" ? themeColors.accent[11] : themeColors.gray[11],
            16,
          ),
        }))}
      />

      <SelectSheet
        open={modelSheetOpen}
        title="Model"
        value={model}
        onChange={(v) => {
          onModelChange(v);
          // If the new model doesn't support reasoning, drop the level so the
          // payload stays consistent. Default reasoning re-applies when
          // switching back to a reasoning-capable model.
          if (!modelSupportsReasoning(v)) {
            onReasoningChange(DEFAULT_REASONING);
          }
        }}
        onClose={() => setModelSheetOpen(false)}
        options={MODELS.map((m) => ({
          value: m.value,
          label: m.label,
          description: m.description,
          icon: <Robot size={16} color={themeColors.gray[11]} />,
        }))}
      />

      <SelectSheet
        open={reasoningSheetOpen}
        title="Reasoning"
        value={reasoning}
        onChange={(v) => onReasoningChange(v as ReasoningEffort)}
        onClose={() => setReasoningSheetOpen(false)}
        options={REASONING_LEVELS.map((r) => ({
          value: r.value,
          label: r.label,
          icon: <BrainIcon size={16} color={themeColors.gray[11]} />,
        }))}
      />

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
  mode: DEFAULT_EXECUTION_MODE,
  model: DEFAULT_MODEL,
  reasoning: DEFAULT_REASONING,
} as const;
