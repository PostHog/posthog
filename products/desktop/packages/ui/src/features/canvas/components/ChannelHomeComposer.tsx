import { isValidConfigValue } from "@posthog/core/task-detail/configOptions";
import { ANALYTICS_EVENTS } from "@posthog/shared/analytics-events";
import type { Task } from "@posthog/shared/domain-types";
import { useQueryClient } from "@tanstack/react-query";
import { useNavigate } from "@tanstack/react-router";
import {
  forwardRef,
  useCallback,
  useImperativeHandle,
  useRef,
  useState,
} from "react";
import { useConnectivity } from "../../../hooks/useConnectivity";
import { track } from "../../../shell/analytics";
import { useOptionalAuthenticatedClient } from "../../auth/authClient";
import { useUserRepositoryIntegration } from "../../integrations/useIntegrations";
import { PromptInput } from "../../message-editor/components/PromptInput";
import { contentToPlainText } from "../../message-editor/content";
import { useDraftStore } from "../../message-editor/draftStore";
import type { EditorHandle } from "../../message-editor/types";
import { toastError } from "../../notifications/errorDetails";
import { ReasoningLevelSelector } from "../../sessions/components/ReasoningLevelSelector";
import { UnifiedModelSelector } from "../../sessions/components/UnifiedModelSelector";
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
import { trackAndCreateCanvas } from "../createCanvasAnalytics";
import { channelFeedQueryKey } from "../hooks/useChannelFeed";
import {
  UNTITLED_CANVAS_NAME,
  useDashboardMutations,
} from "../hooks/useDashboards";
import { useGenerateFreeformCanvas } from "../hooks/useGenerateFreeformCanvas";
import {
  normalizeChannelName,
  PERSONAL_CHANNEL_NAME,
} from "../hooks/useTaskChannels";
import type { PendingKickoff } from "./ChannelFeedView";

export interface ChannelHomeComposerHandle {
  /** Drop a starter prompt into the editor and apply its mode, if any. */
  applySuggestion: (prompt: string, mode?: string) => void;
}

interface ChannelHomeComposerProps {
  channelId: string;
  channelName?: string;
  /** Channel CONTEXT.md, attached to the created task as background. */
  channelContext?: string;
  /** Backend channel UUID that will own the created task (its feed home). */
  backendChannelId?: string;
  onTaskCreated: (task: Task) => void;
  /** Post an optimistic kickoff to the feed the instant a submit is accepted. */
  onPendingStart: (kickoff: PendingKickoff) => void;
  /** Drop that optimistic kickoff once the task is created (or creation fails). */
  onPendingEnd: (id: string) => void;
}

// The prompt box at the bottom of a channel's homepage. A trimmed-down sibling
// of TaskInput: it reuses the same task-creation pipeline (model/mode/reasoning
// preview config + useTaskCreation) but drops the repo/branch pickers — channel
// tasks run repo-less and the agent attaches a repo lazily if it needs one. The
// starter-prompt suggestions render in the parent above the box; this owns the
// local/cloud selector.
export const ChannelHomeComposer = forwardRef<
  ChannelHomeComposerHandle,
  ChannelHomeComposerProps
>(function ChannelHomeComposer(
  {
    channelId,
    channelName,
    channelContext,
    backendChannelId,
    onTaskCreated,
    onPendingStart,
    onPendingEnd,
  },
  ref,
) {
  const sessionId = `channel-home:${channelId}`;
  const editorRef = useRef<EditorHandle>(null);
  const [editorIsEmpty, setEditorIsEmpty] = useState(true);
  const { isOnline } = useConnectivity();
  const navigate = useNavigate();

  // Canvas mode, armed from the mode selector (like Autoresearch on the
  // new-task composer): the next submit generates a canvas from the prompt —
  // create a canvas in the channel, kick off freeform generation, and open it —
  // instead of creating a plain task. This replaces the prompt-to-canvas entry
  // the old channel landing had.
  const [canvasArmed, setCanvasArmed] = useState(false);
  const { createDashboard } = useDashboardMutations();
  const { generate: generateCanvas, isStarting: isStartingCanvas } =
    useGenerateFreeformCanvas({
      channelId,
      channelName: channelName ?? "",
      // The parent already fetches the channel CONTEXT.md; passing it keeps
      // the hook from running its own duplicate fetch.
      channelContext,
    });

  const toggleCanvasMode = useCallback(() => {
    track(ANALYTICS_EVENTS.CHANNEL_ACTION, {
      action_type: "canvas_mode_toggle",
      surface: "channel_home",
      channel_id: channelId,
      armed: !canvasArmed,
    });
    setCanvasArmed(!canvasArmed);
  }, [channelId, canvasArmed]);

  const {
    lastUsedAdapter,
    setLastUsedAdapter,
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
  const setAdapter = useCallback(
    (next: AgentAdapter) => setLastUsedAdapter(next),
    [setLastUsedAdapter],
  );

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
  const setWorkspaceMode = useCallback(
    (mode: WorkspaceMode) => {
      setWorkspaceModeState(mode);
      setLastUsedWorkspaceMode(mode);
      if (mode !== "cloud") setLastUsedLocalWorkspaceMode(mode);
    },
    [setLastUsedWorkspaceMode, setLastUsedLocalWorkspaceMode],
  );

  const { modeOption, modelOption, thoughtOption, isLoading, setConfigOption } =
    usePreviewConfig(adapter);

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

  const queryClient = useQueryClient();
  const apiClient = useOptionalAuthenticatedClient();
  const handleCanvasSubmit = useCallback(async () => {
    const instruction = editorRef.current?.getText().trim();
    if (!instruction || isStartingCanvas) return;
    // The folder→backend channel mapping can still be resolving when the user
    // submits (fresh channel, cold channels list). Resolve it here rather than
    // silently creating a run the feed will never show. The personal channel
    // can't be resolved by name; it only arrives via the channels list.
    let feedChannelId = backendChannelId;
    const normalizedName = channelName ? normalizeChannelName(channelName) : "";
    if (
      !feedChannelId &&
      apiClient &&
      normalizedName &&
      normalizedName !== PERSONAL_CHANNEL_NAME
    ) {
      feedChannelId = await apiClient
        .resolveTaskChannel(normalizedName)
        .then((c) => c.id)
        .catch(() => undefined);
    }
    let record: { id: string; name: string };
    try {
      record = await trackAndCreateCanvas(
        channelId,
        "freeform",
        "channel_home",
        () => createDashboard(channelId, UNTITLED_CANVAS_NAME, "freeform"),
      );
    } catch (error) {
      toastError("Couldn't create canvas", error);
      return;
    }
    // generate() surfaces its own failure toasts; on success it files the task
    // to the channel and tracks completion for the finished-generation toast.
    const taskId = await generateCanvas({
      dashboardId: record.id,
      name: record.name,
      templateId: "freeform",
      instruction,
      // Owned by the backend channel so the run shows as a card in the feed,
      // like a plain composer submit.
      backendChannelId: feedChannelId,
      adapter: adapter ?? "claude",
      model: currentModel,
      reasoningLevel: currentReasoningLevel,
      useStarter: true,
    });
    if (!taskId) return;
    // Surface the new card without waiting for the feed's next poll.
    void queryClient.invalidateQueries({
      queryKey: channelFeedQueryKey(feedChannelId),
    });
    editorRef.current?.clear();
    setCanvasArmed(false);
    void navigate({
      to: "/website/$channelId/dashboards/$dashboardId",
      params: { channelId, dashboardId: record.id },
    });
  }, [
    channelId,
    channelName,
    backendChannelId,
    apiClient,
    adapter,
    currentModel,
    currentReasoningLevel,
    createDashboard,
    generateCanvas,
    isStartingCanvas,
    navigate,
    queryClient,
  ]);

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
    selectedDirectory: "",
    workspaceMode,
    sandboxEnvironmentId:
      workspaceMode === "cloud" && selectedCloudEnvId
        ? selectedCloudEnvId
        : undefined,
    editorIsEmpty,
    adapter,
    executionMode: currentExecutionMode,
    model: currentModel,
    reasoningLevel: currentReasoningLevel,
    allowNoRepo: true,
    channelContext,
    channelName,
    channelId: backendChannelId,
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

  const hints = ["@ to add files", "/ for skills"].join(", ");
  const isBusy = isCreatingTask || isStartingCanvas;
  const submitComposer = canvasArmed ? handleCanvasSubmit : submit;

  return (
    <div className="flex w-full flex-col">
      {/* Canvas generation always runs in the cloud, so the local/cloud pick
          doesn't apply while canvas mode is armed. */}
      {!canvasArmed && (
        <div className="mb-2 flex items-center gap-2">
          <WorkspaceModeSelect
            value={workspaceMode}
            onChange={setWorkspaceMode}
            overrideModes={["local", "cloud"]}
            selectedCloudEnvironmentId={selectedCloudEnvId}
            onCloudEnvironmentChange={setSelectedCloudEnvId}
            size="1"
            disabled={isBusy}
          />
        </div>
      )}

      <PromptInput
        ref={editorRef}
        sessionId={sessionId}
        placeholder={
          canvasArmed
            ? "Describe the canvas to build — the agent generates and publishes it"
            : `What do you want to ship? ${hints}`
        }
        editorHeight="large"
        disabled={isBusy}
        isLoading={isBusy}
        autoFocus
        clearOnSubmit={false}
        submitDisabledExternal={
          canvasArmed
            ? editorIsEmpty || isBusy || !isOnline
            : !canSubmit || isBusy || !isOnline || isLoading
        }
        modeOption={modeOption}
        onModeChange={handleModeChange}
        allowBypassPermissions={allowBypassPermissions}
        canvas={{ active: canvasArmed, onToggle: toggleCanvasMode }}
        enableCommands
        enableBashMode={false}
        modelSelector={
          <UnifiedModelSelector
            modelOption={modelOption}
            adapter={adapter ?? "claude"}
            onAdapterChange={setAdapter}
            disabled={isBusy}
            isConnecting={isLoading}
            onModelChange={handleModelChange}
          />
        }
        reasoningSelector={
          !isLoading && (
            <ReasoningLevelSelector
              thoughtOption={thoughtOption}
              adapter={adapter}
              onChange={handleThoughtChange}
              disabled={isBusy}
            />
          )
        }
        onEmptyChange={setEditorIsEmpty}
        onSubmitClick={() => void submitComposer()}
        onSubmit={() => {
          if (canvasArmed || canSubmit) void submitComposer();
        }}
      />
    </div>
  );
});
