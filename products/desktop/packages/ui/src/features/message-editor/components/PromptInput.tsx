import "./message-editor.css";
import type { SessionConfigOption } from "@agentclientprotocol/sdk";
import { ArrowUp, StopCircle } from "@phosphor-icons/react";
import { InputGroup, InputGroupAddon, InputGroupButton } from "@posthog/quill";
import { SHORTCUTS } from "@posthog/ui/features/command/keyboard-shortcuts";
import type { PromptRecallHandler } from "@posthog/ui/features/sessions/components/chat-thread/composerPromptRecall";
import { cycleModeOption } from "@posthog/ui/features/sessions/sessionStore";
import { useSettingsStore } from "@posthog/ui/features/settings/settingsStore";
import { hasOpenOverlay } from "@posthog/ui/utils/overlay";
import { Flex, Text, Tooltip } from "@radix-ui/themes";
import { EditorContent } from "@tiptap/react";
import clsx from "clsx";
import { forwardRef, useCallback, useEffect, useImperativeHandle } from "react";
import { useHotkeys } from "react-hotkeys-hook";
import { useSkills } from "../../skills/useSkills";
import { skillToEditorCommand } from "../commands";
import { ModeSelector } from "../components/ModeSelector";
import { useDraftStore } from "../draftStore";
import { useTiptapEditor } from "../tiptap/useTiptapEditor";
import type { EditorHandle } from "../types";
import { AttachmentMenu } from "./AttachmentMenu";
import { AttachmentsBar } from "./AttachmentsBar";
import { SlotMachineSubmit } from "./SlotMachineSubmit";

export type { EditorHandle };

export interface PromptInputProps {
  sessionId: string;
  placeholder?: string;
  // editor state
  disabled?: boolean;
  isLoading?: boolean;
  autoFocus?: boolean;
  isActiveSession?: boolean;
  submitDisabledExternal?: boolean;
  clearOnSubmit?: boolean;
  // session context
  taskId?: string;
  repoPath?: string | null;
  // mode
  modeOption?: SessionConfigOption;
  onModeChange?: (value: string) => void;
  allowBypassPermissions?: boolean;
  /**
   * When provided, the mode dropdown gains an "Autoresearch" toggle as its
   * last item (new-task composer only). `active` drives its checkmark.
   */
  autoresearch?: {
    active: boolean;
    onToggle: () => void;
  };
  /**
   * When provided, the mode dropdown gains a "Canvas" toggle (channels
   * composer only). `active` drives its checkmark and the trigger label.
   */
  canvas?: {
    active: boolean;
    onToggle: () => void;
  };
  // capabilities
  enableBashMode?: boolean;
  enableCommands?: boolean;
  // toolbar slots
  modelSelector?: React.ReactElement | null | false;
  reasoningSelector?: React.ReactElement | null | false;
  messagingModeToggle?: React.ReactNode;
  historyButton?: React.ReactNode;
  /**
   * Rendered inside the composer box, above the editor — for mode chrome
   * that must read as part of the input itself (e.g. autoresearch controls)
   * rather than a separate widget attached outside it.
   */
  headerAddon?: React.ReactNode;
  // Render an empty toolbar (no attach/mode/model/reasoning/history/submit).
  // Submission falls back to the Enter key. Used by surfaces that want the
  // editor chrome without any controls yet (e.g. the canvas composer).
  hideDefaultToolbar?: boolean;
  // prompt history provider
  getPromptHistory?: () => string[];
  // plain Up/Down at the caret boundary recalls sent prompts into the input
  onPromptRecall?: PromptRecallHandler;
  // callbacks
  onBeforeSubmit?: (text: string, clearEditor: () => void) => boolean;
  onSubmit?: (text: string) => void;
  onBashCommand?: (command: string) => void;
  onBashModeChange?: (isBashMode: boolean) => void;
  onCancel?: () => void;
  /**
   * Whether the composer is currently editing a queued message in place. When
   * true, Escape abandons the edit (via {@link onCancelEdit}) instead of
   * stopping the running turn.
   */
  isEditingQueued?: boolean;
  onCancelEdit?: () => void;
  onToggleMessagingMode?: () => void;
  onAttachFiles?: (files: File[]) => void;
  onEmptyChange?: (isEmpty: boolean) => void;
  onFocus?: () => void;
  onBlur?: () => void;
  // manual submit override (for flows like new-task that submit outside the editor hook)
  onSubmitClick?: () => unknown;
  submitTooltipOverride?: string;
  editorHeight?: "default" | "large";
  tourTarget?: string;
}

export const PromptInput = forwardRef<EditorHandle, PromptInputProps>(
  (
    {
      sessionId,
      placeholder = "Type a message...",
      disabled = false,
      isLoading = false,
      autoFocus = false,
      isActiveSession = true,
      submitDisabledExternal = false,
      clearOnSubmit,
      taskId,
      repoPath,
      modeOption,
      onModeChange,
      allowBypassPermissions = false,
      autoresearch,
      canvas,
      enableBashMode = false,
      enableCommands = true,
      modelSelector,
      reasoningSelector,
      messagingModeToggle,
      historyButton,
      headerAddon,
      hideDefaultToolbar = false,
      getPromptHistory,
      onPromptRecall,
      onBeforeSubmit,
      onSubmit,
      onBashCommand,
      onBashModeChange,
      onCancel,
      isEditingQueued = false,
      onCancelEdit,
      onToggleMessagingMode,
      onAttachFiles,
      onEmptyChange,
      onFocus,
      onBlur,
      onSubmitClick,
      submitTooltipOverride,
      editorHeight = "default",
      tourTarget,
    },
    ref,
  ) => {
    const focusRequested = useDraftStore((s) => s.focusRequested[sessionId]);
    const clearFocusRequest = useDraftStore((s) => s.actions.clearFocusRequest);
    const slotMachineMode = useSettingsStore((s) => s.slotMachineMode);
    const { data: skills } = useSkills();

    const {
      editor,
      isReady,
      isEmpty,
      isBashMode,
      submit,
      focus,
      blur,
      clear,
      getText,
      getContent,
      setContent,
      insertEditorContent,
      insertChip,
      removeChipById,
      replaceChipAttrs,
      attachments,
      addAttachment,
      removeAttachment,
    } = useTiptapEditor({
      sessionId,
      taskId,
      placeholder,
      disabled,
      submitDisabled: submitDisabledExternal,
      isLoading,
      autoFocus,
      clearOnSubmit,
      context: { taskId, repoPath: repoPath ?? undefined },
      capabilities: {
        bashMode: enableBashMode,
        commands: enableCommands,
      },
      getPromptHistory,
      onPromptRecall,
      onBeforeSubmit,
      onSubmit,
      onBashCommand,
      onBashModeChange,
      onEmptyChange,
      onFocus,
      onBlur,
    });

    useImperativeHandle(
      ref,
      () => ({
        focus,
        blur,
        clear,
        isEmpty: () => isEmpty,
        getContent,
        getText,
        setContent,
        insertEditorContent,
        insertChip,
        removeChipById,
        replaceChipAttrs,
        addAttachment,
        removeAttachment,
      }),
      [
        focus,
        blur,
        clear,
        isEmpty,
        getContent,
        getText,
        setContent,
        insertEditorContent,
        insertChip,
        removeChipById,
        replaceChipAttrs,
        addAttachment,
        removeAttachment,
      ],
    );

    useEffect(() => {
      if (!focusRequested || !isReady) return;
      focus();
      clearFocusRequest(sessionId);
    }, [focusRequested, focus, clearFocusRequest, sessionId, isReady]);

    // Populate the draft-store skills list as a fallback for the / command
    // popup. The agent emits an `available_commands_update` shortly after a
    // session starts, but typing `/` before that arrives would otherwise show
    // only the built-in /good /bad /feedback commands.
    useEffect(() => {
      if (!enableCommands || !skills) return;
      useDraftStore
        .getState()
        .actions.setCommands(sessionId, skills.map(skillToEditorCommand));
      return () => {
        useDraftStore.getState().actions.clearCommands(sessionId);
      };
    }, [sessionId, enableCommands, skills]);

    useHotkeys(
      "escape",
      (e) => {
        if (hasOpenOverlay()) return;
        if (!isActiveSession) return;
        // Editing a queued message: Escape abandons the edit. It takes priority
        // over stopping a running turn — while editing, Escape just cancels.
        if (isEditingQueued && onCancelEdit) {
          e.preventDefault();
          onCancelEdit();
          return;
        }
        if (isLoading && onCancel) {
          e.preventDefault();
          onCancel();
        }
      },
      {
        enableOnFormTags: true,
        enableOnContentEditable: true,
        enabled:
          (isEditingQueued && !!onCancelEdit) || (isLoading && !!onCancel),
      },
      [isActiveSession, isLoading, onCancel, isEditingQueued, onCancelEdit],
    );

    useHotkeys(
      "shift+tab",
      (e) => {
        if (!editor?.isFocused) return;
        if (hasOpenOverlay()) return;
        if (!modeOption || !onModeChange) return;
        const nextMode = cycleModeOption(modeOption, {
          allowBypassPermissions,
        });
        if (!nextMode) return;
        e.preventDefault();
        onModeChange(nextMode);
      },
      {
        enableOnFormTags: true,
        enableOnContentEditable: true,
        enabled: !disabled && !!modeOption && !!onModeChange,
      },
      [editor, modeOption, onModeChange, allowBypassPermissions, disabled],
    );

    useHotkeys(
      SHORTCUTS.SWITCH_MESSAGING_MODE,
      (e) => {
        if (!editor?.isFocused) return;
        if (hasOpenOverlay()) return;
        if (!onToggleMessagingMode) return;
        e.preventDefault();
        onToggleMessagingMode();
      },
      {
        enableOnFormTags: true,
        enableOnContentEditable: true,
        enabled: !disabled && !!onToggleMessagingMode,
      },
      [editor, onToggleMessagingMode, disabled],
    );

    const handleContainerClick = useCallback(
      (e: React.MouseEvent) => {
        const target = e.target as HTMLElement;
        if (
          !target.closest("button") &&
          !target.closest('[role="menu"]') &&
          !target.closest(".ProseMirror")
        ) {
          focus();
        }
      },
      [focus],
    );

    const handleContextMenu = useCallback((e: React.MouseEvent) => {
      e.stopPropagation();
    }, []);

    const doSubmit = useCallback(() => {
      if (onSubmitClick) {
        onSubmitClick();
      } else {
        submit();
      }
    }, [onSubmitClick, submit]);

    const handleSubmitClick = (e: React.MouseEvent) => {
      e.stopPropagation();
      doSubmit();
    };

    const submitBlocked = submitDisabledExternal || isEmpty;
    const submitTooltip =
      submitTooltipOverride ??
      (submitBlocked ? "Enter a message" : "Send message");

    // Stop takes priority over everything: you cancel a run, you don't gamble
    // on it. With slot machine mode on, the send affordance moves out to the
    // pull-lever mounted beside the composer, so the toolbar slot is empty.
    const inStopMode = isLoading && !!onCancel;
    const submitButton = inStopMode ? (
      <Tooltip content="Stop">
        <InputGroupButton
          variant="destructive"
          size="icon-sm"
          onClick={onCancel}
          aria-label="Stop"
        >
          <StopCircle size={14} weight="fill" />
        </InputGroupButton>
      </Tooltip>
    ) : slotMachineMode ? null : (
      <Tooltip content={submitTooltip}>
        <InputGroupButton
          variant="primary"
          size="icon-sm"
          onClick={handleSubmitClick}
          disabled={submitBlocked}
          aria-label="Send message"
          {...(tourTarget && { "data-tour": `${tourTarget}-submit` })}
        >
          <ArrowUp size={14} weight="bold" />
        </InputGroupButton>
      </Tooltip>
    );

    return (
      <Flex direction="column" gap="1">
        <Flex gap="2" align="stretch">
          <InputGroup
            onClick={handleContainerClick}
            onContextMenu={handleContextMenu}
            className={`h-auto flex-1 cursor-text bg-card ${isBashMode ? "ring-1 ring-blue-9" : "focus-within:border-ring/50 focus-within:ring-3 focus-within:ring-ring/30"}`}
            {...(tourTarget && {
              "data-tour": `${tourTarget}-editor`,
              "data-tour-ready": !isEmpty ? "true" : undefined,
            })}
          >
            {headerAddon && (
              <InputGroupAddon align="block-start">
                {headerAddon}
              </InputGroupAddon>
            )}
            {attachments.length > 0 && (
              <InputGroupAddon align="block-start">
                <AttachmentsBar
                  attachments={attachments}
                  onRemove={removeAttachment}
                />
              </InputGroupAddon>
            )}
            <div
              className={clsx(
                "cli-editor-scroll relative min-h-[50px] w-full flex-1 overflow-y-auto px-2 py-2 text-[14px]",
                editorHeight === "large" ? "max-h-[45vh]" : "max-h-[200px]",
              )}
            >
              <EditorContent editor={editor} />
            </div>
            <InputGroupAddon align="block-end" className="p-1">
              {!hideDefaultToolbar && (
                <>
                  <AttachmentMenu
                    disabled={disabled}
                    repoPath={repoPath}
                    taskId={taskId}
                    onAddAttachment={addAttachment}
                    onAttachFiles={onAttachFiles}
                    onInsertChip={insertChip}
                    onRemoveChip={removeChipById}
                  />
                  {onModeChange && (
                    <ModeSelector
                      modeOption={modeOption}
                      onChange={onModeChange}
                      allowBypassPermissions={allowBypassPermissions}
                      disabled={disabled}
                      autoresearch={autoresearch}
                      canvas={canvas}
                    />
                  )}
                  {modelSelector && <span>{modelSelector}</span>}
                  {reasoningSelector && <span>{reasoningSelector}</span>}
                  {messagingModeToggle && <span>{messagingModeToggle}</span>}
                  {isBashMode && (
                    <Text className="font-mono text-(--blue-9) text-[13px]">
                      ! bash
                    </Text>
                  )}
                </>
              )}
              {/* Submit stays even with a blank toolbar; only the left-side
                  addons are suppressed. */}
              <span className="ml-auto flex items-center gap-1">
                {!hideDefaultToolbar && historyButton}
                {submitButton}
              </span>
            </InputGroupAddon>
          </InputGroup>
          {slotMachineMode && !inStopMode && (
            <SlotMachineSubmit
              disabled={submitBlocked}
              onSubmit={doSubmit}
              tourTarget={tourTarget}
            />
          )}
        </Flex>
      </Flex>
    );
  },
);

PromptInput.displayName = "PromptInput";
