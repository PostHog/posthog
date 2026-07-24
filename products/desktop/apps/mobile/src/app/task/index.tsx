import { Text } from "@components/text";
import { LinearGradient } from "expo-linear-gradient";
import { Stack, useLocalSearchParams, useRouter } from "expo-router";
import {
  ArrowUp,
  BrainIcon,
  CaretDown,
  GithubLogo,
  MicrophoneIcon,
  PaperclipIcon,
  PauseIcon,
  PencilIcon,
  Robot,
  ShieldCheck,
  Sparkle,
  StopIcon,
} from "phosphor-react-native";
import { useCallback, useState } from "react";
import {
  ActivityIndicator,
  Pressable,
  ScrollView,
  TextInput,
  View,
} from "react-native";
import {
  useKeyboardHandler,
  useReanimatedKeyboardAnimation,
} from "react-native-keyboard-controller";
import Animated, { runOnJS, useAnimatedStyle } from "react-native-reanimated";
import { useVoiceRecording } from "@/features/chat";
import { usePreferencesStore } from "@/features/preferences/stores/preferencesStore";
import { createTask, runTaskInCloud } from "@/features/tasks/api";
import { GitHubConnectionPrompt } from "@/features/tasks/components/GitHubConnectionPrompt";
import { GitHubLoadNotice } from "@/features/tasks/components/GitHubLoadNotice";
import { AttachmentSheet } from "@/features/tasks/composer/attachments/AttachmentSheet";
import { AttachmentsBar } from "@/features/tasks/composer/attachments/AttachmentsBar";
import { buildCloudPromptBlocks } from "@/features/tasks/composer/attachments/buildCloudPrompt";
import { serializeCloudPrompt } from "@/features/tasks/composer/attachments/cloudPrompt";
import {
  captureFromCamera,
  pickDocument,
  pickPhotoFromLibrary,
} from "@/features/tasks/composer/attachments/pickers";
import type { PendingAttachment } from "@/features/tasks/composer/attachments/types";
import { DotBackground } from "@/features/tasks/composer/DotBackground";
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
} from "@/features/tasks/composer/options";
import { Pill } from "@/features/tasks/composer/Pill";
import { RepositoryPickerInline } from "@/features/tasks/composer/RepositoryPickerInline";
import { SelectSheet } from "@/features/tasks/composer/SelectSheet";
import { useUserIntegrations } from "@/features/tasks/hooks/useUserIntegrations";
import { useWarmTask } from "@/features/tasks/hooks/useWarmTask";
import { pendingPromptRecoveryStoreApi } from "@/features/tasks/stores/pendingPromptRecoveryStore";
import {
  generatePendingTaskKey,
  pendingTaskPromptStoreApi,
} from "@/features/tasks/stores/pendingTaskPromptStore";
import { useTaskStore } from "@/features/tasks/stores/taskStore";
import type {
  CreateTaskOptions,
  RepositorySelection,
} from "@/features/tasks/types";
import {
  findRepositoryOption,
  isRepositorySelectionComplete,
  toRepositorySelection,
} from "@/features/tasks/utils/repositorySelection";
import { useScreenInsets } from "@/hooks/useScreenInsets";
import { logger } from "@/lib/logger";
import { toRgba, useThemeColors } from "@/lib/theme";

const log = logger.scope("task-create");

const SUGGESTIONS = [
  "Create or update my CLAUDE.md file",
  "Search for a TODO comment and fix it",
  "Recommend areas to improve our tests",
] as const;

function modeIcon(mode: ExecutionMode, color: string, size = 14) {
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

export default function NewTaskScreen() {
  const {
    prompt: initialPrompt,
    repo: initialRepo,
    signalReport,
  } = useLocalSearchParams<{
    prompt?: string;
    repo?: string;
    signalReport?: string;
  }>();
  const router = useRouter();
  const themeColors = useThemeColors();
  const { insets, bottom } = useScreenInsets();
  const keyboard = useReanimatedKeyboardAnimation();
  const restingBottom = bottom("compact");
  const {
    error,
    hasGithubIntegration,
    repositoryOptions,
    repositoryWarning,
    isLoading,
    isRefreshingInBackground,
    refetch,
    getUserIntegrationId,
  } = useUserIntegrations();

  const containerStyle = useAnimatedStyle(() => {
    const kbHeight = -keyboard.height.value;
    const progress = keyboard.progress.value;
    return {
      paddingBottom: kbHeight + restingBottom * (1 - progress),
    };
  });

  const suggestionsStyle = useAnimatedStyle(() => ({
    opacity: 1 - keyboard.progress.value,
  }));

  const [keyboardActive, setKeyboardActive] = useState(false);
  useKeyboardHandler(
    {
      onStart: (event) => {
        "worklet";
        runOnJS(setKeyboardActive)(event.height > 0);
      },
    },
    [],
  );

  // Default the repo to the URL param (deep-link from a signal report etc.),
  // falling back to the most recently used repo so the user doesn't have to
  // re-pick the same one for every new task.
  const lastRepository = useTaskStore((s) => s.lastRepository);
  const setLastRepository = useTaskStore((s) => s.setLastRepository);
  const setComposerConfig = useTaskStore((s) => s.setComposerConfig);
  const [prompt, setPrompt] = useState(initialPrompt ?? "");
  const [selection, setSelectionState] = useState<RepositorySelection>(() => {
    if (initialRepo) {
      const match = repositoryOptions.find(
        (o) => o.repository.toLowerCase() === initialRepo.toLowerCase(),
      );
      if (match) return toRepositorySelection(match);
      // Repo known but integration not yet loaded — set repo, integrationId will resolve later
      return { integrationId: null, repository: initialRepo };
    }
    return lastRepository;
  });
  const setSelection = useCallback(
    (next: RepositorySelection) => {
      setSelectionState(next);
      setLastRepository(next);
    },
    [setLastRepository],
  );
  const [mode, setMode] = useState<ExecutionMode>(() => {
    const prefs = usePreferencesStore.getState();
    if (prefs.defaultInitialTaskMode === "last_used") {
      const last = prefs.lastNewTaskMode;
      const isValidMode = EXECUTION_MODES.some((m) => m.value === last);
      if (isValidMode) return last as ExecutionMode;
    }
    return DEFAULT_EXECUTION_MODE;
  });
  const [model, setModel] = useState<string>(DEFAULT_MODEL);
  const [reasoning, setReasoning] = useState<ReasoningEffort>(() => {
    const prefs = usePreferencesStore.getState();
    const isValidReasoning = (v: string): v is ReasoningEffort =>
      REASONING_LEVELS.some((r) => r.value === v);
    const desired =
      prefs.defaultReasoningEffort === "last_used"
        ? prefs.lastUsedReasoningEffort
        : prefs.defaultReasoningEffort;
    return isValidReasoning(desired) ? desired : DEFAULT_REASONING;
  });
  const [creating, setCreating] = useState(false);
  const [repoSheetOpen, setRepoSheetOpen] = useState(false);
  const [modeSheetOpen, setModeSheetOpen] = useState(false);
  const [modelSheetOpen, setModelSheetOpen] = useState(false);
  const [reasoningSheetOpen, setReasoningSheetOpen] = useState(false);
  const [attachments, setAttachments] = useState<PendingAttachment[]>([]);
  const [attachmentSheetOpen, setAttachmentSheetOpen] = useState(false);

  const appendTranscript = useCallback((transcript: string) => {
    setPrompt((prev) => (prev ? `${prev} ${transcript}` : transcript));
  }, []);

  const {
    status: voiceStatus,
    startRecording,
    stopRecording,
    cancelRecording,
  } = useVoiceRecording({ onTranscript: appendTranscript });
  const isRecording = voiceStatus === "recording";
  const isTranscribing = voiceStatus === "transcribing";

  const handleMicPress = useCallback(async () => {
    if (isRecording) {
      await stopRecording();
    } else if (!isTranscribing) {
      await startRecording();
    }
  }, [isRecording, isTranscribing, startRecording, stopRecording]);

  const handleMicLongPress = useCallback(async () => {
    if (isRecording) {
      await cancelRecording();
    }
  }, [isRecording, cancelRecording]);

  const addAttachment = useCallback(
    async (picker: () => Promise<PendingAttachment | null>) => {
      try {
        const att = await picker();
        if (att) setAttachments((prev) => [...prev, att]);
      } catch (err) {
        log.error("Failed to pick attachment", err);
      }
    },
    [],
  );

  const removeAttachment = useCallback((id: string) => {
    setAttachments((prev) => prev.filter((a) => a.id !== id));
  }, []);

  const selectedRepositoryOption = findRepositoryOption(
    repositoryOptions,
    selection,
  );
  const repositoryLabel = selectedRepositoryOption
    ? repositoryOptions.filter(
        (option) => option.repository === selectedRepositoryOption.repository,
      ).length > 1
      ? `${selectedRepositoryOption.repository} · ${selectedRepositoryOption.integrationLabel}`
      : selectedRepositoryOption.repository
    : "Select repository…";
  const repositoryLoadBlocked =
    !!repositoryWarning && repositoryOptions.length === 0;

  const handleCreateTask = useCallback(async () => {
    const hasContent = !!prompt.trim() || attachments.length > 0;
    if (!hasContent || !isRepositorySelectionComplete(selection) || creating) {
      return;
    }

    setCreating(true);

    // Echo the prompt into the chat thread the moment the user taps send.
    // The key is transient until `createTask` returns the real task id, at
    // which point we `move` it so the detail screen can pick it up.
    const pendingKey = generatePendingTaskKey();
    const trimmedPrompt = prompt.trim();
    const echoAttachments = attachments.map((a) => ({
      kind: a.kind,
      uri: a.uri,
      fileName: a.fileName,
      mimeType: a.mimeType,
    }));
    pendingTaskPromptStoreApi.set(pendingKey, {
      promptText: trimmedPrompt,
      attachments: echoAttachments.length > 0 ? echoAttachments : undefined,
      setAt: Date.now(),
    });

    // Durably record the prompt so it survives the app being killed before
    // creation completes; cleared once the task exists (or on failure, when
    // the text is still live in the composer).
    if (trimmedPrompt) {
      pendingPromptRecoveryStoreApi.set(pendingKey, trimmedPrompt);
    }

    // Tracks where the optimistic echo currently lives so the catch block
    // can clear the correct key regardless of how far the flow got.
    let currentPendingKey = pendingKey;

    try {
      // The task description is plain text (it shows up as the task title and
      // in metadata). Attachments only enter the agent prompt via the cloud
      // payload below.
      const descriptionText =
        trimmedPrompt ||
        (attachments.length === 1
          ? `Attached: ${attachments[0].fileName}`
          : `Attached ${attachments.length} files`);

      const task = await createTask({
        description: descriptionText,
        title: descriptionText.slice(0, 100),
        repository: selection.repository ?? undefined,
        // User-scoped integration (matches desktop). `selection.integrationId`
        // is the GitHub installation id; map it back to the UserIntegration
        // UUID the API expects. The backend also auto-resolves this from the
        // repository for user-created tasks, so it's a best-effort hint.
        github_user_integration: getUserIntegrationId(selection.integrationId),
        ...(signalReport
          ? {
              origin_product: "signal_report",
              signal_report: signalReport,
              signal_report_task_relationship: "implementation",
            }
          : {}),
      } as CreateTaskOptions);

      pendingTaskPromptStoreApi.move(pendingKey, task.id);
      currentPendingKey = task.id;
      pendingPromptRecoveryStoreApi.clear(pendingKey);

      // Seed the per-task composer config with the mode/model/reasoning the
      // user picked here, so the task detail screen reflects them and every
      // subsequent run (resume-after-terminal) reuses the selected mode rather
      // than falling back to DEFAULT_EXECUTION_MODE ("plan").
      setComposerConfig(task.id, { mode, model, reasoning });

      const pendingUserMessage =
        attachments.length > 0
          ? serializeCloudPrompt(
              await buildCloudPromptBlocks(trimmedPrompt, attachments),
            )
          : trimmedPrompt;

      const supportsReasoning = modelSupportsReasoning(model);

      await runTaskInCloud(task.id, {
        pendingUserMessage,
        runtimeAdapter: "claude",
        model,
        reasoningEffort: supportsReasoning ? reasoning : undefined,
        initialPermissionMode: mode,
        autoPublish: usePreferencesStore.getState().autoPublishCloudRuns,
        rtkEnabled: usePreferencesStore.getState().rtkEnabledCloud,
        ...(signalReport
          ? {
              runSource: "signal_report" as const,
              signalReportId: signalReport,
            }
          : {}),
      });

      router.replace(`/task/${task.id}`);
    } catch (creationError) {
      log.error("Failed to create task", creationError);
      pendingTaskPromptStoreApi.clear(currentPendingKey);
      pendingPromptRecoveryStoreApi.clear(pendingKey);
    } finally {
      setCreating(false);
    }
  }, [
    attachments,
    creating,
    mode,
    model,
    prompt,
    reasoning,
    router,
    selection,
    signalReport,
    getUserIntegrationId,
    setComposerConfig,
  ]);

  const hasContent = !!prompt.trim() || attachments.length > 0;
  const canSubmit =
    hasContent && isRepositorySelectionComplete(selection) && !creating;
  const showReasoningPill = modelSupportsReasoning(model);

  // Best-effort prewarm; failures are swallowed. `selection.integrationId` is
  // the GitHub installation id, not a PostHog integration id — the backend
  // resolves the integration from the repository, so this only keys the warm.
  useWarmTask({
    repository: selection.repository,
    githubIntegrationId: selection.integrationId,
    composerIsEmpty: !hasContent,
    runtimeAdapter: "claude",
    model,
    reasoningEffort: showReasoningPill ? reasoning : null,
  });

  if (isLoading && hasGithubIntegration === null) {
    return (
      <>
        <Stack.Screen
          options={{
            headerShown: true,
            headerTitle: "New task",
            headerStyle: { backgroundColor: themeColors.background },
            headerTintColor: themeColors.gray[12],
            presentation: "modal",
          }}
        />
        <View className="flex-1 items-center justify-center bg-background">
          <ActivityIndicator size="large" color={themeColors.accent[9]} />
          <Text className="mt-4 text-gray-11">Loading repositories...</Text>
        </View>
      </>
    );
  }

  if (error || repositoryLoadBlocked) {
    return (
      <>
        <Stack.Screen
          options={{
            headerShown: true,
            headerTitle: "New task",
            headerStyle: { backgroundColor: themeColors.background },
            headerTintColor: themeColors.gray[12],
            presentation: "modal",
          }}
        />
        <View className="flex-1 justify-center bg-background px-4">
          <GitHubLoadNotice
            message={
              error ??
              repositoryWarning ??
              "Could not load GitHub repositories."
            }
            onRetry={refetch}
          />
        </View>
      </>
    );
  }

  if (hasGithubIntegration === false) {
    return (
      <View className="flex-1 bg-background">
        <View style={{ paddingTop: insets.top + 56 }} className="flex-1">
          <GitHubConnectionPrompt
            onConnected={refetch}
            title="Connect GitHub to continue"
            description="You need to connect your GitHub account before creating tasks. This allows PostHog to work on your repositories."
          />
        </View>
      </View>
    );
  }

  return (
    <>
      <View className="flex-1 bg-background">
        <DotBackground />

        <Animated.View style={[{ flex: 1 }, containerStyle]}>
          <View className="flex-1 items-stretch justify-end px-3">
            {repoSheetOpen ? null : prompt.trim().length === 0 ? (
              <Animated.View
                style={suggestionsStyle}
                pointerEvents={keyboardActive ? "none" : "auto"}
                className="flex-1 justify-end pb-4"
              >
                <Text className="mb-3 px-1 text-[13px] text-gray-10">
                  Suggestions
                </Text>
                <View className="gap-2">
                  {SUGGESTIONS.map((suggestion) => (
                    <Pressable
                      key={suggestion}
                      onPress={() => setPrompt(suggestion)}
                      className="rounded-2xl border border-gray-6 bg-card px-4 py-3 active:bg-gray-2"
                    >
                      <Text className="text-[14px] text-gray-12">
                        {suggestion}
                      </Text>
                    </Pressable>
                  ))}
                </View>
              </Animated.View>
            ) : null}

            {/* Inline repo picker: pops up directly above the pill when
                open, replacing the suggestions area. Rendered inline (not
                a Modal) so it feels like a dropdown anchored to the pill
                rather than a slide-in sheet. */}
            <View className="mb-2">
              <RepositoryPickerInline
                open={repoSheetOpen}
                repositoryOptions={repositoryOptions}
                selected={selectedRepositoryOption}
                loading={isLoading && repositoryOptions.length === 0}
                isRefreshing={isRefreshingInBackground}
                onChange={(option) =>
                  setSelection(toRepositorySelection(option))
                }
                onClose={() => setRepoSheetOpen(false)}
              />
            </View>
          </View>

          <View className="px-3">
            {repositoryWarning ? (
              <GitHubLoadNotice
                message={repositoryWarning}
                onRetry={refetch}
                tone="warning"
              />
            ) : null}

            <View className="mb-2 flex-row">
              <Pressable
                onPress={() => setRepoSheetOpen((prev) => !prev)}
                className={`flex-row items-center gap-2 rounded-full border py-1.5 pr-2.5 pl-2 active:bg-gray-2 ${
                  repoSheetOpen
                    ? "border-accent-7 bg-accent-3"
                    : "border-gray-6 bg-card"
                }`}
              >
                <GithubLogo
                  size={16}
                  color={
                    selectedRepositoryOption
                      ? themeColors.gray[12]
                      : themeColors.gray[10]
                  }
                  weight={selectedRepositoryOption ? "fill" : "regular"}
                />
                <Text
                  className={`text-[13px] ${
                    selectedRepositoryOption ? "text-gray-12" : "text-gray-10"
                  }`}
                  numberOfLines={1}
                >
                  {repositoryLabel}
                </Text>
                <CaretDown
                  size={12}
                  color={themeColors.gray[10]}
                  style={{
                    transform: [{ rotate: repoSheetOpen ? "180deg" : "0deg" }],
                  }}
                />
              </Pressable>
            </View>

            <View className="overflow-hidden rounded-2xl border border-gray-6 bg-card">
              <AttachmentsBar
                attachments={attachments}
                onRemove={removeAttachment}
              />
              <TextInput
                className="px-4 pt-3.5 pb-3 text-[15px] text-gray-12"
                style={{ minHeight: 56, maxHeight: 200 }}
                placeholder="Describe what you want to build…"
                placeholderTextColor={themeColors.gray[9]}
                value={prompt}
                onChangeText={setPrompt}
                multiline
                textAlignVertical="top"
              />

              <View className="flex-row items-center gap-2 px-2 pb-2">
                <Pressable
                  hitSlop={8}
                  onPress={() => setAttachmentSheetOpen(true)}
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

                <View className="relative flex-1">
                  <ScrollView
                    horizontal
                    showsHorizontalScrollIndicator={false}
                    keyboardShouldPersistTaps="handled"
                    contentContainerStyle={{
                      alignItems: "center",
                      gap: 6,
                      paddingRight: 16,
                    }}
                  >
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
                        icon={
                          <BrainIcon size={14} color={themeColors.gray[11]} />
                        }
                        label={reasoningLabel(reasoning)}
                        onPress={() => setReasoningSheetOpen(true)}
                      />
                    ) : null}
                  </ScrollView>
                  {/* Right-edge fade hints that more pills exist when the row
                      overflows. Non-interactive so taps fall through. */}
                  <LinearGradient
                    pointerEvents="none"
                    colors={[toRgba(themeColors.card, 0), themeColors.card]}
                    start={{ x: 0, y: 0.5 }}
                    end={{ x: 1, y: 0.5 }}
                    style={{
                      position: "absolute",
                      top: 0,
                      bottom: 0,
                      right: 0,
                      width: 24,
                    }}
                  />
                </View>

                <Pressable
                  onPress={
                    isTranscribing
                      ? undefined
                      : isRecording
                        ? handleMicPress
                        : hasContent
                          ? handleCreateTask
                          : handleMicPress
                  }
                  onLongPress={handleMicLongPress}
                  disabled={
                    isTranscribing || (hasContent && !canSubmit && !isRecording)
                  }
                  accessibilityLabel={
                    isRecording
                      ? "Stop recording"
                      : hasContent
                        ? "Create task"
                        : "Record voice"
                  }
                  className={`h-9 w-9 items-center justify-center rounded-lg ${
                    canSubmit || isRecording || (!hasContent && !isTranscribing)
                      ? "bg-gray-12"
                      : "bg-gray-5"
                  }`}
                >
                  {creating || isTranscribing ? (
                    <ActivityIndicator
                      size="small"
                      color={themeColors.background}
                    />
                  ) : isRecording ? (
                    <StopIcon
                      size={18}
                      color={themeColors.status.error}
                      weight="fill"
                    />
                  ) : hasContent ? (
                    <ArrowUp
                      size={18}
                      color={
                        canSubmit ? themeColors.background : themeColors.gray[9]
                      }
                      weight="bold"
                    />
                  ) : (
                    <MicrophoneIcon size={18} color={themeColors.background} />
                  )}
                </Pressable>
              </View>
            </View>
          </View>
        </Animated.View>
      </View>

      <SelectSheet
        open={modeSheetOpen}
        title="Execution mode"
        value={mode}
        onChange={(value) => {
          const next = value as ExecutionMode;
          setMode(next);
          usePreferencesStore.getState().setLastNewTaskMode(next);
        }}
        onClose={() => setModeSheetOpen(false)}
        options={EXECUTION_MODES.map((executionMode) => ({
          value: executionMode.value,
          label: executionMode.label,
          description: executionMode.description,
          icon: modeIcon(
            executionMode.value,
            executionMode.value === "plan"
              ? themeColors.accent[11]
              : themeColors.gray[11],
            16,
          ),
        }))}
      />

      <SelectSheet
        open={modelSheetOpen}
        title="Model"
        value={model}
        onChange={(value) => {
          setModel(value);
          if (!modelSupportsReasoning(value)) {
            setReasoning(DEFAULT_REASONING);
          }
        }}
        onClose={() => setModelSheetOpen(false)}
        options={MODELS.map((modelOption) => ({
          value: modelOption.value,
          label: modelOption.label,
          description: modelOption.description,
          icon: <Robot size={16} color={themeColors.gray[11]} />,
        }))}
      />

      <SelectSheet
        open={reasoningSheetOpen}
        title="Reasoning"
        value={reasoning}
        onChange={(value) => {
          const next = value as ReasoningEffort;
          setReasoning(next);
          usePreferencesStore.getState().setLastUsedReasoningEffort(next);
        }}
        onClose={() => setReasoningSheetOpen(false)}
        options={REASONING_LEVELS.map((reasoningLevel) => ({
          value: reasoningLevel.value,
          label: reasoningLevel.label,
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
