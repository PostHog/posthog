import "./message-editor.css";
import type { SessionConfigOption } from "@agentclientprotocol/sdk";
import { ArrowUp, StopCircle } from "@phosphor-icons/react";
import type { FileAttachment } from "@posthog/core/message-editor/content";
import {
  Button,
  InputGroup,
  InputGroupAddon,
  TooltipProvider,
} from "@posthog/quill";
import { SHORTCUTS } from "@posthog/ui/features/command/keyboard-shortcuts";
import type { PromptRecallHandler } from "@posthog/ui/features/sessions/components/chat-thread/composerPromptRecall";
import { cycleModeOption } from "@posthog/ui/features/sessions/sessionStore";
import { useSettingsStore } from "@posthog/ui/features/settings/settingsStore";
import { hasOpenOverlay } from "@posthog/ui/utils/overlay";
import { Flex, Text, Tooltip } from "@radix-ui/themes";
import { EditorContent } from "@tiptap/react";
import clsx from "clsx";
import {
  forwardRef,
  useCallback,
  useEffect,
  useImperativeHandle,
  useState,
} from "react";
import { useHotkeys } from "react-hotkeys-hook";
import { useSkills } from "../../skills/useSkills";
import { skillToEditorCommand } from "../commands";
import { ModeSelector } from "../components/ModeSelector";
import { useDraftStore } from "../draftStore";
import { useTiptapEditor } from "../tiptap/useTiptapEditor";
import type { EditorHandle } from "../types";
import { AttachmentMenu } from "./AttachmentMenu";
import { AttachmentsBar, type AttachmentUploadStatus } from "./AttachmentsBar";
import { SlotMachineSubmit } from "./SlotMachineSubmit";

export type { EditorHandle };

// How long the send button holds its own busy state when the surface never
// reports one — long enough to register as a press, short enough that a send
// the surface silently refuses doesn't strand the spinner.
const SUBMIT_PRESS_FEEDBACK_MS = 800;

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
  /** What the composer starts from when this session has no draft yet. */
  initialContent?: string;
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
  // capabilities
  enableBashMode?: boolean;
  enableCommands?: boolean;
  // toolbar slots
  modelSelector?: React.ReactElement | null | false;
  reasoningSelector?: React.ReactElement | null | false;
  messagingModeToggle?: React.ReactNode;
  historyButton?: React.ReactNode;
  /**
   * Pinned inside the composer box beside the send button — for context the
   * prompt always carries that the user did not attach by hand (e.g. a
   * channel's CONTEXT.md). It sits apart from the attachments row on purpose:
   * hand-picked files come and go, this rides along with every send. The
   * editor reserves its measured width, so keep it a fixed size rather than
   * one that changes on hover.
   */
  submitAdornment?: React.ReactNode;
  /**
   * Pushed to the far end of the composer's toolbar row — for read-only status
   * about the session the prompt goes to (e.g. context usage), as opposed to
   * the controls on the left that change what sending does.
   */
  toolbarEndSlot?: React.ReactNode;
  /**
   * Rendered inside the composer box, above the editor — for mode chrome
   * that must read as part of the input itself (e.g. autoresearch controls)
   * rather than a separate widget attached outside it.
   */
  headerAddon?: React.ReactNode;
  // Drop the toolbar row's own controls (attach/mode/model/reasoning/history).
  // The row itself is omitted unless a caller slot still needs it, and send
  // stays put — it lives in the box, not the row. Used by surfaces that want
  // the editor chrome without any controls yet (e.g. the canvas composer).
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
  onAttachmentsChange?: (attachments: FileAttachment[]) => void;
  attachmentUploadStatuses?: Record<string, AttachmentUploadStatus>;
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
      initialContent,
      taskId,
      repoPath,
      modeOption,
      onModeChange,
      allowBypassPermissions = false,
      autoresearch,
      enableBashMode = false,
      enableCommands = true,
      modelSelector,
      reasoningSelector,
      messagingModeToggle,
      historyButton,
      submitAdornment,
      toolbarEndSlot,
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
      onAttachmentsChange,
      attachmentUploadStatuses,
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
    // Seeded at the send button's own width so the first paint already clears
    // it, rather than laying the text out full-width and reflowing it.
    const [submitClusterWidth, setSubmitClusterWidth] = useState(40);
    // The text's right inset has to clear whatever sits over its bottom-right
    // corner. That used to be the send button alone (a fixed 40px), but an
    // adornment beside it makes the width depend on its content, so measure.
    // A callback ref rather than an effect: the cluster mounts and unmounts
    // with the button, and this re-observes the new node each time.
    const submitClusterRef = useCallback((el: HTMLSpanElement | null) => {
      if (!el) return;
      const observer = new ResizeObserver(([entry]) => {
        // The cluster is inset by 4px (right-1); the same again keeps the text
        // from running up against it.
        setSubmitClusterWidth(entry.contentRect.width + 8);
      });
      observer.observe(el);
      return () => observer.disconnect();
    }, []);

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
      insertSlashCommand,
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
      initialContent,
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
      onAttachmentsChange,
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

    // Instant press feedback. Every surface that owns this composer flips its
    // own busy flags only after a round trip (a usage pre-flight, a worktree
    // probe, the send itself), so without this the button sits inert on click.
    const [pressedSubmit, setPressedSubmit] = useState(false);
    const surfaceBusy = disabled || isLoading || submitDisabledExternal;

    const doSubmit = useCallback(() => {
      setPressedSubmit(true);
      if (onSubmitClick) {
        onSubmitClick();
      } else {
        submit();
      }
    }, [onSubmitClick, submit]);

    // Hand over as soon as the surface reports busy itself, so the two states
    // never fight over the button.
    useEffect(() => {
      if (!pressedSubmit) return;
      if (surfaceBusy) {
        setPressedSubmit(false);
        return;
      }
      const timer = setTimeout(
        () => setPressedSubmit(false),
        SUBMIT_PRESS_FEEDBACK_MS,
      );
      return () => clearTimeout(timer);
    }, [pressedSubmit, surfaceBusy]);

    const handleSubmitClick = (e: React.MouseEvent) => {
      e.stopPropagation();
      doSubmit();
    };

    // `disabled` counts: every caller sets it for a state where sending is
    // impossible or would repeat itself (task creation in flight, a session
    // that is not running, a compacting Pi session), and the editor cannot be
    // typed into, so a live send button only invites a click that misfires.
    const submitBlocked = disabled || submitDisabledExternal || isEmpty;
    // A surface that is loading *and* locked out of typing is working on the
    // send itself, so the button keeps spinning until it lands. A surface that
    // is loading but still typeable is mid-turn and accepting queued messages,
    // where send has to stay live.
    const submitBusy = pressedSubmit || (disabled && isLoading);
    const submitTooltip = submitBusy
      ? "Sending"
      : (submitTooltipOverride ??
        (submitBlocked ? "Enter a message" : "Send message"));

    // Stop takes priority over everything: you cancel a run, you don't gamble
    // on it. With slot machine mode on, the send affordance moves out to the
    // pull-lever mounted beside the composer, so the toolbar slot is empty.
    // A real quill Button, not InputGroupButton: this is the composer's primary
    // action and should carry the design system's raised primary treatment
    // rather than the flat in-field styling. Stop shares the slot, so it uses
    // the same component — otherwise the button would change shape mid-run.
    const inStopMode = isLoading && !!onCancel;
    const submitButton = inStopMode ? (
      <Tooltip content="Stop">
        <Button
          variant="destructive"
          size="icon"
          onClick={onCancel}
          aria-label="Stop"
        >
          <StopCircle size={14} weight="fill" />
        </Button>
      </Tooltip>
    ) : slotMachineMode ? null : (
      <Tooltip content={submitTooltip}>
        <Button
          variant="primary"
          size="icon"
          onClick={handleSubmitClick}
          disabled={submitBlocked || submitBusy}
          loading={submitBusy}
          aria-label="Send message"
          className="rounded-xs"
          {...(tourTarget && { "data-tour": `${tourTarget}-submit` })}
        >
          <ArrowUp size={14} weight="bold" />
        </Button>
      </Tooltip>
    );

    // The controls sit under the box rather than inside it, so the box holds
    // only what you are writing plus the send button. Mirrors the addons' own
    // flex/gap/padding so the row keeps their spacing and left inset, and
    // carries the muted colour the addons would have supplied.
    const toolbar = (!hideDefaultToolbar ||
      toolbarEndSlot ||
      messagingModeToggle) && (
      <div className="flex select-none items-center gap-1 whitespace-nowrap px-1 text-muted-foreground">
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
              // No `/` extension registered means the item would type a bare
              // slash and open nothing, so it hides instead.
              onInsertSlashCommand={
                enableCommands ? insertSlashCommand : undefined
              }
            />
            {/* Direct flex children, not wrapped in a span: an inline wrapper
                builds a line box whose leading pushes the trigger a pixel below
                the toolbar's other buttons. The model chip renders before the
                mode chip so its open menu stays anchored in place while a
                harness switch changes which permission modes exist (and how
                wide their labels are). */}
            {modelSelector}
            {reasoningSelector}
            {onModeChange && (
              <ModeSelector
                modeOption={modeOption}
                onChange={onModeChange}
                allowBypassPermissions={allowBypassPermissions}
                disabled={disabled}
                autoresearch={autoresearch}
              />
            )}
            {isBashMode && (
              <Text className="font-mono text-(--blue-9) text-[13px]">
                ! bash
              </Text>
            )}
          </>
        )}
        <span className="ml-auto flex items-center gap-1">
          {toolbarEndSlot}
          {!hideDefaultToolbar && historyButton}
          {messagingModeToggle}
        </span>
      </div>
    );

    const composerRow = (
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
            <InputGroupAddon align="block-start">{headerAddon}</InputGroupAddon>
          )}
          {attachments.length > 0 && (
            <InputGroupAddon align="block-start">
              {/* One provider for the row: moving between squares reuses the
                    open delay instead of re-waiting it per attachment. */}
              <TooltipProvider>
                <AttachmentsBar
                  attachments={attachments}
                  onRemove={removeAttachment}
                  uploadStatuses={attachmentUploadStatuses}
                />
              </TooltipProvider>
            </InputGroupAddon>
          )}
          {/* Send floats over the text's bottom-right rather than sitting in a
              column beside it. Laid out beside the text, it would push the
              scroll container inwards and strand the scrollbar mid-box; over
              it, the container runs to the edge and the bar hugs it. The text
              reserves the cluster's width so a long line never runs underneath
              — measured rather than fixed, because an adornment beside the
              button makes that width depend on what's in it. */}
          <div className="relative w-full">
            <div
              // Gated on the cluster existing rather than trusting the last
              // measurement: the observer's cleanup can't clear the width, so
              // a cluster that unmounts (slot-machine mode, then the adornment
              // removed) would otherwise leave its gutter behind for good.
              style={{
                paddingRight:
                  submitButton || submitAdornment ? submitClusterWidth : 8,
              }}
              className={clsx(
                "cli-editor-scroll relative min-h-[37px] w-full overflow-y-auto py-2 pl-2 text-[14px]",
                editorHeight === "large" ? "max-h-[45vh]" : "max-h-[200px]",
                // A disabled editor still looks editable: the caret is the only
                // tell, and it is absent precisely because you cannot focus it.
                disabled && "text-muted-foreground",
                // What you are typing in bash mode is a shell command, so it
                // should look like one.
                isBashMode && "font-mono",
              )}
            >
              <EditorContent editor={editor} />
            </div>
            {(submitButton || submitAdornment) && (
              <span
                ref={submitClusterRef}
                className="absolute right-1 bottom-1 flex items-center gap-1"
              >
                {submitAdornment}
                {submitButton}
              </span>
            )}
          </div>
        </InputGroup>
        {slotMachineMode && !inStopMode && (
          <SlotMachineSubmit
            disabled={submitBlocked || submitBusy}
            onSubmit={doSubmit}
            tourTarget={tourTarget}
          />
        )}
      </Flex>
    );

    return (
      <Flex direction="column" gap="1">
        {composerRow}
        {toolbar}
      </Flex>
    );
  },
);

PromptInput.displayName = "PromptInput";
