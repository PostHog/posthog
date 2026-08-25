import type {
  PiModelSelection,
  PiThinkingLevel,
} from "@posthog/core/pi-runtime/piSessionController";
import { isValidConfigValue } from "@posthog/core/task-detail/configOptions";
import type { AgentRuntime } from "@posthog/shared";
import type { Task } from "@posthog/shared/domain-types";
import {
  forwardRef,
  useCallback,
  useEffect,
  useImperativeHandle,
  useRef,
  useState,
} from "react";
import { useConnectivity } from "../../../hooks/useConnectivity";
import { toast } from "../../../primitives/toast";
import { useChannelWikiContext } from "../../context-wiki/hooks/useContextWiki";
import { useContextLayerFlag } from "../../feature-flags/useContextLayerFlag";
import { useFeatureFlag } from "../../feature-flags/useFeatureFlag";
import { useFeatureFlagsLoaded } from "../../feature-flags/useFeatureFlagsLoaded";
import { useUserRepositoryIntegration } from "../../integrations/useIntegrations";
import { PromptInput } from "../../message-editor/components/PromptInput";
import { contentToPlainText } from "../../message-editor/content";
import { useDraftStore } from "../../message-editor/draftStore";
import type { EditorHandle } from "../../message-editor/types";
import { PiModelSelector } from "../../pi-sessions/PiSessionControls";
import { usePiModelCatalog } from "../../pi-sessions/usePiModelCatalog";
import type { AgentHarness } from "../../sessions/components/HarnessSubmenu";
import { ReasoningLevelSelector } from "../../sessions/components/ReasoningLevelSelector";
import { getCurrentModeFromConfigOptions } from "../../sessions/sessionStore";
import {
  type AgentAdapter,
  useSettingsStore,
} from "../../settings/settingsStore";
import {
  type WorkspaceMode,
  WorkspaceModeSelect,
} from "../../task-detail/components/WorkspaceModeSelect";
import { useCloudModeEnabled } from "../../task-detail/hooks/useCloudModeEnabled";
import { usePreviewConfig } from "../../task-detail/hooks/usePreviewConfig";
import { useTaskCreation } from "../../task-detail/hooks/useTaskCreation";
import { resolveWorkspaceModePreference } from "../../task-detail/hooks/workspaceModePreference";
import { useUpdateTaskChannelRepositories } from "../hooks/useTaskChannels";
import {
  resolveTaskRepositoryDraft,
  useTaskRepositoryDraftStore,
} from "../stores/taskRepositoryDraftStore";
import type { PendingKickoff } from "./ChannelFeedView";
import {
  TaskRepositoryChip,
  TaskRepositoryDialog,
} from "./TaskRepositoryDialog";

export interface ChannelHomeComposerHandle {
  /** Drop a starter prompt into the editor and apply its mode, if any. */
  applySuggestion: (prompt: string, mode?: string) => void;
}

interface ChannelHomeComposerProps {
  /** Backend channel UUID that owns the created task (its feed home). */
  channelId: string;
  channelName?: string;
  /** Channel CONTEXT.md, attached to the created task as background. */
  channelContext?: string;
  channelRepositories?: string[];
  channelGithubIntegration?: number | null;
  onTaskCreated: (task: Task) => void;
  /** Post an optimistic kickoff to the feed the instant a submit is accepted. */
  onPendingStart: (kickoff: PendingKickoff) => void;
  /** Drop that optimistic kickoff once the task is created (or creation fails). */
  onPendingEnd: (id: string) => void;
}

// The prompt box at the bottom of a channel's homepage. A trimmed-down sibling
// of TaskInput: it reuses the same task-creation pipeline (model/mode/reasoning
// preview config + useTaskCreation) but drops the branch picker. Tasks default
// to the space's repositories; the chip beside the local/cloud selector swaps
// in a task-specific repository or folder selection. The starter-prompt
// suggestions render in the parent above the box; this owns the selector row.
export const ChannelHomeComposer = forwardRef<
  ChannelHomeComposerHandle,
  ChannelHomeComposerProps
>(function ChannelHomeComposer(
  {
    channelId,
    channelName,
    channelContext,
    channelRepositories = [],
    channelGithubIntegration = null,
    onTaskCreated,
    onPendingStart,
    onPendingEnd,
  },
  ref,
) {
  const sessionId = `channel-home:${channelId}`;
  const contextLayerEnabled = useContextLayerFlag();
  const wiki = useChannelWikiContext(channelId, contextLayerEnabled);
  const effectiveChannelContext = wiki.useLegacy ? channelContext : undefined;
  const editorRef = useRef<EditorHandle>(null);
  const [editorIsEmpty, setEditorIsEmpty] = useState(true);
  const { isOnline } = useConnectivity();

  const {
    lastUsedAdapter,
    setLastUsedAdapter,
    lastUsedAgentRuntime,
    setLastUsedAgentRuntime,
    lastUsedPiModel,
    setLastUsedPiModel,
    lastUsedWorkspaceMode,
    setLastUsedWorkspaceMode,
    setLastUsedLocalWorkspaceMode,
    allowBypassPermissions,
    defaultInitialTaskMode,
    lastUsedInitialTaskMode,
    setLastUsedReasoningEffort,
    setLastUsedModel,
  } = useSettingsStore();

  const adapter = lastUsedAdapter;
  const [runtime, setRuntime] = useState<AgentRuntime>("acp");
  // Keep the menu open when a harness switch swaps its ACP/Pi control.
  const [modelMenuOpen, setModelMenuOpen] = useState(false);
  const didResolveRuntimeRef = useRef(false);
  const [selectedPiModelId, setSelectedPiModelId] = useState<string | null>(
    null,
  );
  const [selectedPiThinkingLevel, setSelectedPiThinkingLevel] =
    useState<PiThinkingLevel | null>(null);
  const piHarnessEnabled = useFeatureFlag("pi-harness");
  const flagsLoaded = useFeatureFlagsLoaded();
  const { data: piModelCatalog = [], isPending: isPiConfigLoading } =
    usePiModelCatalog(runtime === "pi");

  const setAdapter = useCallback(
    (next: AgentAdapter) => setLastUsedAdapter(next),
    [setLastUsedAdapter],
  );

  useEffect(() => {
    if (didResolveRuntimeRef.current || !flagsLoaded) {
      return;
    }

    didResolveRuntimeRef.current = true;
    setRuntime(
      piHarnessEnabled && lastUsedAgentRuntime === "pi" ? "pi" : "acp",
    );
  }, [flagsLoaded, lastUsedAgentRuntime, piHarnessEnabled]);

  const cloudModeEnabled = useCloudModeEnabled();
  const { hasGithubIntegration } = useUserRepositoryIntegration();

  // Repo-less channel tasks only run local or cloud (worktree needs a repo), so
  // collapse any lingering worktree preference down to local for the initial pick.
  const [workspaceMode, setWorkspaceModeState] = useState<WorkspaceMode>(() =>
    resolveWorkspaceModePreference({
      preferredMode: lastUsedWorkspaceMode === "cloud" ? "cloud" : "local",
      cloudModeEnabled,
      hasGithubIntegration,
      lastUsedLocalWorkspaceMode: "local",
    }),
  );
  const [selectedCloudEnvId, setSelectedCloudEnvId] = useState<string | null>(
    null,
  );
  const [selectedCustomImageId, setSelectedCustomImageId] = useState<
    string | null
  >(null);
  const [repositoryDialogOpen, setRepositoryDialogOpen] = useState(false);
  const repositoryDraft = useTaskRepositoryDraftStore(
    (s) => s.drafts[channelId],
  );
  const setRepositoryDraft = useTaskRepositoryDraftStore((s) => s.setDraft);
  const {
    repositories: taskRepositories,
    githubIntegration: taskGithubIntegration,
    folder: taskFolder,
  } = resolveTaskRepositoryDraft(
    repositoryDraft,
    channelRepositories,
    channelGithubIntegration,
  );
  const updateChannelRepositories = useUpdateTaskChannelRepositories();
  const setWorkspaceMode = useCallback(
    (mode: WorkspaceMode) => {
      setWorkspaceModeState(mode);
      setLastUsedWorkspaceMode(mode);
      if (mode !== "cloud") setLastUsedLocalWorkspaceMode(mode);
    },
    [setLastUsedWorkspaceMode, setLastUsedLocalWorkspaceMode],
  );

  const {
    modeOption,
    modelOption,
    thoughtOption,
    contextWindowOption,
    fastModeOption,
    isLoading,
    setConfigOption,
  } = usePreviewConfig(adapter);

  const currentModel =
    modelOption?.type === "select" ? modelOption.currentValue : undefined;
  const adapterDefault = adapter === "codex" ? "auto" : "plan";
  const modeFallback =
    defaultInitialTaskMode === "last_used" &&
    lastUsedInitialTaskMode &&
    isValidConfigValue(modeOption, lastUsedInitialTaskMode)
      ? lastUsedInitialTaskMode
      : adapterDefault;
  const currentExecutionMode =
    getCurrentModeFromConfigOptions(modeOption ? [modeOption] : undefined) ??
    modeFallback;
  const currentReasoningLevel =
    thoughtOption?.type === "select" ? thoughtOption.currentValue : undefined;
  const currentContextWindow =
    contextWindowOption?.type === "select" &&
    (contextWindowOption.currentValue === "200k" ||
      contextWindowOption.currentValue === "1m")
      ? contextWindowOption.currentValue
      : undefined;
  const currentFastMode =
    fastModeOption?.type === "select"
      ? fastModeOption.currentValue === "on"
      : undefined;
  const currentPiModel =
    piModelCatalog.find((model) => model.id === selectedPiModelId) ??
    piModelCatalog.find((model) => model.id === lastUsedPiModel) ??
    piModelCatalog.find((model) => model.isDefault) ??
    piModelCatalog[0];
  const piThinkingLevels = currentPiModel?.thinkingLevels ?? [];
  const currentPiThinkingLevel = piThinkingLevels.includes(
    selectedPiThinkingLevel ?? "high",
  )
    ? (selectedPiThinkingLevel ?? "high")
    : piThinkingLevels[0];
  const supportsPiThinking = piThinkingLevels.some((level) => level !== "off");
  const taskModel = runtime === "pi" ? currentPiModel?.id : currentModel;
  const taskReasoningLevel =
    runtime === "pi"
      ? supportsPiThinking
        ? currentPiThinkingLevel
        : undefined
      : currentReasoningLevel;

  // In-flight optimistic kickoff ids, oldest first. Submits are serialized
  // (the composer is disabled while creating), so retiring the oldest on each
  // task-ready callback matches create order and keeps adds/removes balanced —
  // no row is ever orphaned, even if two creates briefly overlap.
  const pendingIdsRef = useRef<string[]>([]);

  const handleTaskCreated = useCallback(
    (task: Task) => {
      // onTaskCreated swaps the real card in; drop the matching "Starting…"
      // row in the same tick so the two never show at once.
      onTaskCreated(task);
      const id = pendingIdsRef.current.shift();
      if (id) onPendingEnd(id);
    },
    [onTaskCreated, onPendingEnd],
  );

  const { isCreatingTask, canSubmit, handleSubmit } = useTaskCreation({
    editorRef,
    sessionId,
    selectedDirectory: taskFolder,
    repositories: workspaceMode === "cloud" ? taskRepositories : undefined,
    githubIntegrationId:
      workspaceMode === "cloud"
        ? (taskGithubIntegration ?? undefined)
        : undefined,
    workspaceMode,
    sandboxEnvironmentId:
      workspaceMode === "cloud" && selectedCloudEnvId
        ? selectedCloudEnvId
        : undefined,
    customImageId:
      workspaceMode === "cloud" && selectedCustomImageId
        ? selectedCustomImageId
        : undefined,
    editorIsEmpty,
    adapter,
    runtime,
    executionMode: runtime === "pi" ? undefined : currentExecutionMode,
    model: taskModel,
    reasoningLevel: taskReasoningLevel,
    contextWindow: runtime === "pi" ? undefined : currentContextWindow,
    fastMode: runtime === "pi" ? undefined : currentFastMode,
    allowNoRepo: true,
    channelContext: effectiveChannelContext,
    channelContextPath: wiki.path,
    submissionBlocked: wiki.blocked,
    channelName,
    channelId,
    channelContextId: channelId,
    onTaskCreated: handleTaskCreated,
  });

  // Own the submit so the composer clears the instant a keystroke is accepted
  // (not after the create round trip), which is what stops the "looks like it
  // didn't take" double-submit. We snapshot the content and hand it to
  // handleSubmit as an override so clearing early can't race the read.
  const submit = useCallback(async () => {
    const editor = editorRef.current;
    if (!editor || !canSubmit) return;
    const content = editor.getContent();
    const prompt = contentToPlainText(content).trim();
    if (!prompt) return;

    editor.clear();
    const id =
      globalThis.crypto?.randomUUID?.() ??
      `pending-${prompt.length}-${Date.now()}`;
    pendingIdsRef.current.push(id);
    onPendingStart({ id, prompt });

    const created = await handleSubmit(content);
    if (!created) {
      // Creation failed — onTaskCreated never fired, so this id is still
      // queued. Pull its row and give the full structured prompt (chips and
      // attachments, not just flattened text) back so the user can retry.
      pendingIdsRef.current = pendingIdsRef.current.filter((p) => p !== id);
      onPendingEnd(id);
      editor.insertEditorContent(content);
    }
  }, [canSubmit, handleSubmit, onPendingStart, onPendingEnd]);

  const handleModeChange = useCallback(
    (value: string) => {
      if (modeOption) setConfigOption(modeOption.id, value);
    },
    [modeOption, setConfigOption],
  );
  const handleModelChange = useCallback(
    (value: string) => {
      if (modelOption) {
        setConfigOption(modelOption.id, value);
        setLastUsedModel(value);
      }
    },
    [modelOption, setConfigOption, setLastUsedModel],
  );
  const handleThoughtChange = useCallback(
    (value: string) => {
      if (thoughtOption) {
        setConfigOption(thoughtOption.id, value);
        setLastUsedReasoningEffort(value);
      }
    },
    [thoughtOption, setConfigOption, setLastUsedReasoningEffort],
  );
  const handleRuntimeChange = useCallback(
    (nextRuntime: AgentRuntime) => {
      didResolveRuntimeRef.current = true;
      setRuntime(nextRuntime);
      setLastUsedAgentRuntime(nextRuntime);
    },
    [setLastUsedAgentRuntime],
  );
  const handleHarnessChange = useCallback(
    (harness: AgentHarness) => {
      if (harness === "pi") {
        handleRuntimeChange("pi");
        return;
      }

      handleRuntimeChange("acp");
      setAdapter(harness);
    },
    [handleRuntimeChange, setAdapter],
  );
  const handlePiModelChange = useCallback(
    (model: PiModelSelection) => {
      setSelectedPiModelId(model.id);
      setLastUsedPiModel(model.id);
    },
    [setLastUsedPiModel],
  );
  const handlePiThinkingLevelChange = useCallback((level: PiThinkingLevel) => {
    setSelectedPiThinkingLevel(level);
  }, []);

  useImperativeHandle(
    ref,
    () => ({
      applySuggestion: (prompt: string, mode?: string) => {
        // Pending content (not setContent) preserves the multi-line template's
        // line breaks and focuses at the end; mirrors the new-task screen.
        useDraftStore.getState().actions.setPendingContent(sessionId, {
          segments: [{ type: "text", text: prompt }],
        });
        if (mode && isValidConfigValue(modeOption, mode)) {
          setConfigOption(modeOption.id, mode);
        }
      },
    }),
    [sessionId, modeOption, setConfigOption],
  );

  const isBusy = isCreatingTask;

  return (
    <div className="relative flex w-full flex-col">
      {/* The row sits in normal flow above the input, mirroring the new-task
          page's composer (the composer scrolls with the feed, so nothing may
          float over the cards below). */}
      <div className="mb-1 flex min-w-0 items-center gap-1">
        <WorkspaceModeSelect
          value={workspaceMode}
          onChange={setWorkspaceMode}
          overrideModes={["local", "cloud"]}
          selectedCloudEnvironmentId={selectedCloudEnvId}
          onCloudEnvironmentChange={setSelectedCloudEnvId}
          selectedCustomImageId={selectedCustomImageId}
          onCustomImageChange={setSelectedCustomImageId}
          size="1"
          disabled={isBusy}
        />
        <TaskRepositoryChip
          cloud={workspaceMode === "cloud"}
          repositoryCount={taskRepositories.length}
          hasFolder={!!taskFolder}
          disabled={isBusy}
          onOpen={() => setRepositoryDialogOpen(true)}
        />
      </div>

      <TaskRepositoryDialog
        open={repositoryDialogOpen}
        onOpenChange={setRepositoryDialogOpen}
        cloud={workspaceMode === "cloud"}
        repositories={taskRepositories}
        integrationId={taskGithubIntegration}
        folder={taskFolder}
        onApply={(selection) => {
          setRepositoryDraft(channelId, {
            repositories: selection.repositories,
            githubIntegration: selection.integrationId,
            folder: selection.folder,
          });
          if (selection.saveToSpace && workspaceMode === "cloud") {
            updateChannelRepositories.mutate(
              {
                channelId,
                githubIntegration: selection.integrationId,
                repositories: selection.repositories,
              },
              {
                onError: () =>
                  toast.error("Couldn't save repositories to the space"),
              },
            );
          }
        }}
      />

      <PromptInput
        ref={editorRef}
        sessionId={sessionId}
        placeholder="What do you want to ship?"
        editorHeight="large"
        disabled={isBusy}
        isLoading={isBusy}
        autoFocus
        clearOnSubmit={false}
        submitDisabledExternal={
          !canSubmit ||
          isBusy ||
          !isOnline ||
          (runtime === "pi" ? isPiConfigLoading : isLoading) ||
          (runtime === "pi" && !currentPiModel)
        }
        modeOption={runtime === "pi" ? undefined : modeOption}
        onModeChange={runtime === "pi" ? undefined : handleModeChange}
        allowBypassPermissions={allowBypassPermissions}
        enableCommands
        enableBashMode={false}
        modelSelector={
          runtime === "pi" ? (
            <PiModelSelector
              models={piModelCatalog}
              currentModel={currentPiModel}
              thinkingLevel={
                supportsPiThinking ? currentPiThinkingLevel : undefined
              }
              thinkingLevels={piThinkingLevels}
              disabled={isBusy || isPiConfigLoading}
              isLoading={isPiConfigLoading}
              onChange={handlePiModelChange}
              onThinkingLevelChange={handlePiThinkingLevelChange}
              onHarnessChange={handleHarnessChange}
              menuOpen={modelMenuOpen}
              onMenuOpenChange={setModelMenuOpen}
            />
          ) : null
        }
        reasoningSelector={
          runtime === "pi" ? null : (
            <ReasoningLevelSelector
              thoughtOption={thoughtOption}
              modelOption={modelOption}
              adapter={adapter ?? "claude"}
              contextWindowOption={contextWindowOption}
              fastModeOption={fastModeOption}
              onChange={handleThoughtChange}
              onModelChange={handleModelChange}
              onAdapterChange={setAdapter}
              onHarnessChange={
                piHarnessEnabled ? handleHarnessChange : undefined
              }
              includePiHarness={piHarnessEnabled}
              onConfigOptionChange={setConfigOption}
              menuOpen={modelMenuOpen}
              onMenuOpenChange={setModelMenuOpen}
              disabled={isBusy}
              isLoading={isLoading}
            />
          )
        }
        onEmptyChange={setEditorIsEmpty}
        onSubmitClick={() => void submit()}
        onSubmit={() => {
          if (canSubmit) void submit();
        }}
      />
    </div>
  );
});
