import {
  contentToXml,
  type EditorContent,
  type FileAttachment,
  isContentEmpty,
  type MentionChip,
} from "@posthog/core/message-editor/content";
import { buildGithubRefPlaceholderChip } from "@posthog/core/message-editor/githubIssueChip";
import {
  type ParsedGithubIssueUrl,
  parseGithubIssueUrl,
} from "@posthog/core/message-editor/githubIssueUrl";
import {
  type AutoConvertedPaste,
  buildMarkdownLink,
  buildPastedTextLabel,
  extractBashCommand,
  isBashModeText,
  isRepeatOfAutoConvertedPaste,
  isUrlOnly,
  shouldAutoConvertLongText,
} from "@posthog/core/message-editor/paste";
import {
  formatHotkey,
  SHORTCUTS,
} from "@posthog/ui/features/command/keyboard-shortcuts";
import {
  PROMPT_RECALL_HINT_KEY,
  type PromptRecallHandler,
} from "@posthog/ui/features/sessions/components/chat-thread/composerPromptRecall";
import { sessionStoreSetters } from "@posthog/ui/features/sessions/sessionStore";
import { useSettingsStore as useFeatureSettingsStore } from "@posthog/ui/features/settings/settingsStore";
import { type ToastOptions, toast } from "@posthog/ui/primitives/toast";
import { isSendMessageSubmitKey } from "@posthog/ui/utils/sendMessageKey";
import type { Node as ProseMirrorNode } from "@tiptap/pm/model";
import { TextSelection } from "@tiptap/pm/state";
import type { EditorView } from "@tiptap/pm/view";
import { useEditor } from "@tiptap/react";
import type React from "react";
import { useCallback, useEffect, useRef, useState } from "react";
import { getGithubIssue, getGithubPullRequest } from "../hostApi";
import { usePasteUndoStore } from "../pasteUndoStore";
import { usePromptHistoryStore } from "../promptHistoryStore";
import { findChipRangeById } from "../tiptap/chipRange";
import { getEditorExtensions } from "../tiptap/extensions";
import {
  type DraftContext,
  editorContentToTiptapJson,
  useDraftSync,
} from "../tiptap/useDraftSync";
import { htmlToMarkdown } from "../utils/htmlToMarkdown";
import {
  persistImageFile,
  persistTextContent,
  resolveAndAttachDroppedFiles,
} from "../utils/persistFile";

export interface UseTiptapEditorOptions {
  sessionId: string;
  taskId?: string;
  placeholder?: string;
  disabled?: boolean;
  submitDisabled?: boolean;
  isLoading?: boolean;
  autoFocus?: boolean;
  context?: DraftContext;
  capabilities?: {
    fileMentions?: boolean;
    commands?: boolean;
    bashMode?: boolean;
  };
  clearOnSubmit?: boolean;
  getPromptHistory?: () => string[];
  onPromptRecall?: PromptRecallHandler;
  onBeforeSubmit?: (text: string, clearEditor: () => void) => boolean;
  onSubmit?: (text: string) => void;
  onBashCommand?: (command: string) => void;
  onBashModeChange?: (isBashMode: boolean) => void;
  onEmptyChange?: (isEmpty: boolean) => void;
  onFocus?: () => void;
  onBlur?: () => void;
}

const EDITOR_CLASS =
  "cli-editor min-h-[1.5em] w-full break-words border-none bg-transparent pr-2 text-[14px] text-[var(--gray-12)] outline-none [overflow-wrap:break-word] [white-space:pre-wrap] [word-break:break-word]";

interface TrackedAutoConvertedPaste extends AutoConvertedPaste {
  kind: "file" | "github-ref";
  status: "pending" | "inserted" | "canceled";
}

function insertChipWithTrailingSpace(
  view: EditorView,
  attrs: {
    type: MentionChip["type"];
    id: string;
    label: string;
    pastedText?: boolean;
    chipId?: string;
  },
): void {
  const chipNode = view.state.schema.nodes.mentionChip.create({
    pastedText: false,
    ...attrs,
  });
  const space = view.state.schema.text(" ");
  const { tr } = view.state;
  tr.replaceSelectionWith(chipNode).insert(tr.selection.from, space);
  view.dispatch(tr);
}

async function pasteTextAsFile(
  view: EditorView,
  text: string,
  pasteCountRef: React.MutableRefObject<number>,
  tracked?: TrackedAutoConvertedPaste,
): Promise<void> {
  const result = await persistTextContent(text);
  if (tracked?.status === "canceled") return;
  pasteCountRef.current += 1;
  const lineCount = text.split("\n").length;
  insertChipWithTrailingSpace(view, {
    type: "file",
    id: result.path,
    label: buildPastedTextLabel(pasteCountRef.current, lineCount),
    pastedText: true,
    chipId: tracked?.chipId,
  });
  if (tracked) tracked.status = "inserted";
  view.focus();
}

function insertGithubRefPlaceholder(
  view: EditorView,
  parsed: ParsedGithubIssueUrl,
  chipId: string,
): void {
  insertChipWithTrailingSpace(view, {
    ...buildGithubRefPlaceholderChip(parsed),
    chipId,
  });
}

function replaceChipWithText(
  view: EditorView,
  chipId: string,
  text: string,
): boolean {
  const { doc, selection } = view.state;
  const range = findChipRangeById(doc, chipId);
  if (!range) return false;
  // Only treat it as a double paste while the caret still follows the chip.
  if (selection.from !== range.to && selection.from !== range.to - 1) {
    return false;
  }
  view.dispatch(view.state.tr.insertText(text, range.from, range.to));
  view.focus();
  return true;
}

async function fetchGithubRefTitle(
  parsed: ParsedGithubIssueUrl,
): Promise<string | null> {
  const input = {
    owner: parsed.owner,
    repo: parsed.repo,
    number: parsed.number,
  };
  try {
    if (parsed.kind === "pr") {
      const pr = await getGithubPullRequest(input);
      return pr?.title ?? null;
    }
    const issue = await getGithubIssue(input);
    return issue?.title ?? null;
  } catch {
    return null;
  }
}

async function resolveGithubRefChip(
  view: EditorView,
  parsed: ParsedGithubIssueUrl,
  chipId: string,
): Promise<void> {
  const title = await fetchGithubRefTitle(parsed);
  const resolvedLabel =
    title !== null ? `#${parsed.number} - ${title}` : `#${parsed.number}`;

  if (view.isDestroyed) return;

  const { doc } = view.state;
  const range = findChipRangeById(doc, chipId);
  if (!range) return;
  const node = doc.nodeAt(range.from);
  if (!node) return;
  view.dispatch(
    view.state.tr.setNodeMarkup(range.from, undefined, {
      ...node.attrs,
      label: resolvedLabel,
    }),
  );
}

function replaceComposerText(view: EditorView, text = "") {
  const tr = view.state.tr.delete(1, view.state.doc.content.size - 1);
  return text ? tr.insertText(text, 1) : tr;
}

function hasVisibleSuggestionPopup(sessionId: string): boolean {
  // tippy.js sets data-state="hidden" when hiding via .hide(); the session
  // tag keeps another mounted composer's popup from matching.
  return (
    document.querySelector(
      `[data-tippy-root] .tippy-box:not([data-state='hidden']) [data-suggestion-session="${CSS.escape(sessionId)}"]`,
    ) !== null
  );
}

function showHintOnce(
  key: string,
  title: string,
  detail: string | ToastOptions,
): void {
  const store = useFeatureSettingsStore.getState();
  if (!store.shouldShowHint(key)) return;
  store.recordHintShown(key);
  toast.info(title, detail);
}

function showMessageNavHint(): void {
  showHintOnce(
    PROMPT_RECALL_HINT_KEY,
    "Recalled a sent prompt",
    `Use ${formatHotkey(SHORTCUTS.MESSAGE_PREV)} and ${formatHotkey(SHORTCUTS.MESSAGE_NEXT)} to jump between your messages in the conversation.`,
  );
}

function showPasteHint(message: string, description: string): void {
  const key =
    message === "Pasted as file attachment" ? "paste-as-file" : "paste-inline";
  showHintOnce(key, message, {
    description,
    action: {
      label: "Got it",
      onClick: () => useFeatureSettingsStore.getState().markHintLearned(key),
    },
  });
}

export function useTiptapEditor(options: UseTiptapEditorOptions) {
  const {
    sessionId,
    taskId,
    placeholder = "",
    disabled = false,
    submitDisabled = false,
    isLoading = false,
    autoFocus = false,
    context,
    capabilities = {},
    clearOnSubmit = true,
    getPromptHistory,
    onPromptRecall,
    onBeforeSubmit,
    onSubmit,
    onBashCommand,
    onBashModeChange,
    onEmptyChange,
    onFocus,
    onBlur,
  } = options;

  const {
    fileMentions = true,
    commands = true,
    bashMode: enableBashMode = true,
  } = capabilities;

  const callbackRefs = useRef({
    onBeforeSubmit,
    onSubmit,
    onBashCommand,
    onBashModeChange,
    onEmptyChange,
    onFocus,
    onBlur,
  });
  callbackRefs.current = {
    onBeforeSubmit,
    onSubmit,
    onBashCommand,
    onBashModeChange,
    onEmptyChange,
    onFocus,
    onBlur,
  };

  const submitDisabledRef = useRef(submitDisabled);
  submitDisabledRef.current = submitDisabled;

  const getPromptHistoryRef = useRef(getPromptHistory);
  getPromptHistoryRef.current = getPromptHistory;

  const onPromptRecallRef = useRef(onPromptRecall);
  onPromptRecallRef.current = onPromptRecall;

  // Doc snapshot taken when arrow-key recall first replaces the input, so
  // arrowing back down past the newest prompt restores what was being typed
  // (kept as a ProseMirror node to preserve mention chips).
  const promptRecallDraftRef = useRef<ProseMirrorNode | null>(null);

  const prevBashModeRef = useRef(false);
  const prevIsEmptyRef = useRef(true);
  const submitRef = useRef<() => void>(() => {});
  const draftRef = useRef<ReturnType<typeof useDraftSync> | null>(null);

  const pasteCountRef = useRef(0);
  const lastAutoConvertedPasteRef = useRef<TrackedAutoConvertedPaste | null>(
    null,
  );
  useEffect(() => {
    return () => {
      if (lastAutoConvertedPasteRef.current) {
        usePasteUndoStore.getState().setUndoableChipId(null);
      }
    };
  }, []);
  const historyActions = usePromptHistoryStore.getState();
  const [isEmptyState, setIsEmptyState] = useState(true);
  const [isReady, setIsReady] = useState(false);
  const [attachments, setAttachments] = useState<FileAttachment[]>([]);
  const attachmentsRef = useRef<FileAttachment[]>([]);

  const editor = useEditor(
    {
      extensions: getEditorExtensions({
        sessionId,
        placeholder,
        fileMentions,
        commands,
      }),
      editable: !disabled,
      autofocus: autoFocus ? "end" : false,
      editorProps: {
        attributes: { class: EDITOR_CLASS, spellcheck: "false" },
        handleDOMEvents: {
          click: (_view, event) => {
            const target = (event.target as HTMLElement).closest("a");
            if (target) {
              event.preventDefault();
              return true;
            }
            return false;
          },
        },
        handleKeyDown: (view, event) => {
          if (
            event.key === "v" &&
            (event.metaKey || event.ctrlKey) &&
            event.shiftKey
          ) {
            event.preventDefault();
            (async () => {
              try {
                const text = await navigator.clipboard.readText();
                if (!text?.trim()) return;
                useFeatureSettingsStore
                  .getState()
                  .markHintLearned("paste-inline");
                await pasteTextAsFile(view, text, pasteCountRef);
              } catch (_error) {
                toast.error("Failed to paste as file attachment");
              }
            })();
            return true;
          }

          if (isSendMessageSubmitKey(event)) {
            if (!view.editable || submitDisabledRef.current) return false;
            if (hasVisibleSuggestionPopup(sessionId)) return false;
            event.preventDefault();
            historyActions.reset();
            submitRef.current();
            return true;
          }

          if (
            (event.key === "ArrowUp" || event.key === "ArrowDown") &&
            // Plain arrows only: Shift+Arrow selects, and Alt/Cmd/Ctrl arrow
            // chords are global shortcuts handled elsewhere.
            !event.shiftKey &&
            !event.altKey &&
            !event.metaKey &&
            !event.ctrlKey
          ) {
            const historyGetter = getPromptHistoryRef.current;
            if (!taskId && !historyGetter && !onPromptRecallRef.current) {
              return false;
            }

            const currentText = view.state.doc.textContent;
            const isEmpty = !currentText.trim();

            const history = historyGetter?.() ?? [];

            if (event.key === "ArrowUp" && isEmpty) {
              if (taskId) {
                const queuedContent =
                  sessionStoreSetters.dequeueMessagesAsText(taskId);
                if (queuedContent !== null && queuedContent !== undefined) {
                  event.preventDefault();
                  view.dispatch(replaceComposerText(view, queuedContent));
                  return true;
                }
              }

              const newText = historyActions.navigateUp(history, currentText);
              if (newText !== null) {
                event.preventDefault();
                view.dispatch(replaceComposerText(view, newText));
                return true;
              }
            }

            if (event.key === "ArrowDown" && isEmpty) {
              const newText = historyActions.navigateDown(history);
              if (newText !== null) {
                event.preventDefault();
                view.dispatch(replaceComposerText(view, newText));
                return true;
              }
            }

            const recallPrompt = onPromptRecallRef.current;
            if (recallPrompt) {
              if (hasVisibleSuggestionPopup(sessionId)) return false;

              const { selection, doc } = view.state;
              // Arrows move the caret as usual; only a press that can't
              // travel further (caret already at the first or last position)
              // hands off to sent-prompt recall.
              const atBoundary =
                selection.empty &&
                (event.key === "ArrowUp"
                  ? selection.from <= 1
                  : selection.to >= doc.content.size - 1);
              if (!atBoundary) return false;

              const result = recallPrompt(event.key === "ArrowUp" ? -1 : 1);
              if (!result) return false;
              event.preventDefault();

              if (result.kind === "recall") {
                if (result.fresh) {
                  promptRecallDraftRef.current = view.state.doc;
                  showMessageNavHint();
                }
                const tr = replaceComposerText(view, result.text);
                // Recalling up parks the caret at the start so the next Up
                // press keeps cycling; recalling down parks it at the end.
                if (event.key === "ArrowUp") {
                  tr.setSelection(TextSelection.create(tr.doc, 1));
                }
                view.dispatch(tr);
                return true;
              }

              const draft = promptRecallDraftRef.current;
              promptRecallDraftRef.current = null;
              if (draft) {
                const tr = view.state.tr.replaceWith(
                  0,
                  view.state.doc.content.size,
                  draft.content,
                );
                tr.setSelection(TextSelection.atEnd(tr.doc));
                view.dispatch(tr);
              } else {
                view.dispatch(replaceComposerText(view));
              }
              return true;
            }
          }

          return false;
        },
        handleDrop: (_view, event, _slice, moved) => {
          if (moved) return false;

          const files = event.dataTransfer?.files;
          if (!files || files.length === 0) return false;

          event.preventDefault();

          resolveAndAttachDroppedFiles(files, (a) => {
            setAttachments((prev) => {
              if (prev.some((existing) => existing.id === a.id)) return prev;
              return [...prev, a];
            });
          }).catch(() => toast.error("Failed to attach files"));

          return true;
        },
        handlePaste: (view, event) => {
          const { from, to } = view.state.selection;
          const clipboardText = event.clipboardData?.getData("text/plain");
          const trimmedClipboardText = clipboardText?.trim();

          // Only the immediately-following paste can undo an auto-conversion.
          const lastConverted = lastAutoConvertedPasteRef.current;
          lastAutoConvertedPasteRef.current = null;
          if (lastConverted) {
            usePasteUndoStore.getState().setUndoableChipId(null);
          }

          // Auto-wrap selected text as markdown link when pasting a URL
          if (
            from !== to &&
            trimmedClipboardText &&
            isUrlOnly(trimmedClipboardText)
          ) {
            event.preventDefault();
            const selectedText = view.state.doc.textBetween(from, to);
            const linkMarkdown = buildMarkdownLink(
              selectedText,
              trimmedClipboardText,
            );
            view.dispatch(
              view.state.tr.replaceWith(
                from,
                to,
                view.state.schema.text(linkMarkdown),
              ),
            );
            return true;
          }

          // Pasting the same clipboard again undoes the chip auto-conversion
          if (
            from === to &&
            isRepeatOfAutoConvertedPaste(lastConverted, clipboardText)
          ) {
            if (
              replaceChipWithText(
                view,
                lastConverted.chipId,
                lastConverted.insertText,
              )
            ) {
              event.preventDefault();
              if (lastConverted.kind === "file") {
                useFeatureSettingsStore
                  .getState()
                  .markHintLearned("paste-as-file");
              }
              return true;
            }
            if (lastConverted.status === "pending") {
              event.preventDefault();
              lastConverted.status = "canceled";
              useFeatureSettingsStore
                .getState()
                .markHintLearned("paste-as-file");
              view.dispatch(view.state.tr.insertText(lastConverted.insertText));
              return true;
            }
          }

          // Auto-convert a pasted GitHub issue or PR URL into a chip
          if (from === to && clipboardText && trimmedClipboardText) {
            const parsedRef = parseGithubIssueUrl(trimmedClipboardText);
            if (parsedRef) {
              event.preventDefault();
              const chipId = crypto.randomUUID();
              insertGithubRefPlaceholder(view, parsedRef, chipId);
              lastAutoConvertedPasteRef.current = {
                clipboardText,
                insertText: clipboardText,
                chipId,
                kind: "github-ref",
                status: "inserted",
              };
              void resolveGithubRefChip(view, parsedRef, chipId);
              return true;
            }
          }

          const items = event.clipboardData?.items;
          if (!items) return false;

          const imageItems: DataTransferItem[] = [];
          for (let i = 0; i < items.length; i++) {
            const item = items[i];
            if (item.type.startsWith("image/")) {
              imageItems.push(item);
            }
          }

          if (imageItems.length > 0) {
            event.preventDefault();

            (async () => {
              for (const item of imageItems) {
                const file = item.getAsFile();
                if (!file) continue;

                try {
                  const result = await persistImageFile(file);

                  setAttachments((prev) => {
                    if (prev.some((a) => a.id === result.path)) return prev;
                    return [...prev, { id: result.path, label: result.name }];
                  });
                } catch (_error) {
                  toast.error("Failed to paste image");
                }
              }
            })();

            return true;
          }

          // Editor is plain-text, so preserve pasted formatting as Markdown.
          const html = event.clipboardData?.getData("text/html");
          const markdown = html ? htmlToMarkdown(html, clipboardText) : null;
          const effectiveText = markdown ?? clipboardText;

          // Auto-convert long pasted text into a file attachment
          const autoConvertThreshold =
            useFeatureSettingsStore.getState().autoConvertLongText;
          if (
            effectiveText &&
            shouldAutoConvertLongText(effectiveText, autoConvertThreshold)
          ) {
            event.preventDefault();

            const tracked: TrackedAutoConvertedPaste = {
              clipboardText: clipboardText || effectiveText,
              insertText: effectiveText,
              chipId: crypto.randomUUID(),
              kind: "file",
              status: "pending",
            };
            lastAutoConvertedPasteRef.current = tracked;
            usePasteUndoStore.getState().setUndoableChipId(tracked.chipId);

            (async () => {
              try {
                await pasteTextAsFile(
                  view,
                  effectiveText,
                  pasteCountRef,
                  tracked,
                );
                if (tracked.status !== "canceled") {
                  showPasteHint(
                    "Pasted as file attachment",
                    "Paste again to expand as text.",
                  );
                }
              } catch (_error) {
                if (tracked.status !== "canceled") {
                  toast.error("Failed to convert pasted text to attachment");
                }
              }
            })();

            return true;
          }

          // Insert inline; ProseMirror would otherwise drop the HTML formatting.
          if (markdown) {
            event.preventDefault();
            view.dispatch(view.state.tr.insertText(markdown, from, to));
            return true;
          }

          if (clipboardText && clipboardText.length > 200) {
            showPasteHint(
              "Pasted as text",
              "Use ⌘⇧V to paste as a file attachment instead.",
            );
          }

          return false;
        },
      },
      onCreate: () => {
        setIsReady(true);
        const content = draftRef.current?.getContent();
        const newIsEmpty = isContentEmpty(content ?? null);
        setIsEmptyState(newIsEmpty);
        prevIsEmptyRef.current = newIsEmpty;
        callbackRefs.current.onEmptyChange?.(newIsEmpty);
      },
      onUpdate: ({ editor: e }) => {
        const text = e.getText();
        const newBashMode = enableBashMode && isBashModeText(text);

        if (newBashMode !== prevBashModeRef.current) {
          prevBashModeRef.current = newBashMode;
          callbackRefs.current.onBashModeChange?.(newBashMode);
        }

        draftRef.current?.saveDraft(e, attachmentsRef.current);
        const content = draftRef.current?.getContent(attachmentsRef.current);
        const newIsEmpty = isContentEmpty(content ?? null);
        setIsEmptyState(newIsEmpty);

        if (newIsEmpty !== prevIsEmptyRef.current) {
          prevIsEmptyRef.current = newIsEmpty;
          callbackRefs.current.onEmptyChange?.(newIsEmpty);
        }

        e.commands.scrollIntoView();
      },
      onFocus: () => {
        callbackRefs.current.onFocus?.();
      },
      onBlur: () => {
        callbackRefs.current.onBlur?.();
      },
    },
    [sessionId, disabled, fileMentions, commands, placeholder],
  );

  const draft = useDraftSync(editor, sessionId, context);
  draftRef.current = draft;

  // biome-ignore lint/correctness/useExhaustiveDependencies: `editor` is the trigger: a recreated editor brings a new schema, and restoring a snapshot taken against the old one would throw on replaceWith.
  useEffect(() => {
    promptRecallDraftRef.current = null;
  }, [editor]);

  // Keep attachmentsRef in sync with state (synchronous, no effect needed)
  attachmentsRef.current = attachments;

  // Re-save draft when attachments change so persistence stays up to date
  useEffect(() => {
    if (editor) {
      draftRef.current?.saveDraft(editor, attachments);
    }
  }, [attachments, editor]);

  // Notify parent when emptiness changes due to attachment add/remove.
  // Only reacts to attachment changes; text changes are handled by onUpdate.
  // We read editor text directly because isEmptyState may include stale
  // attachment info (isContentEmpty counts attachments in its input).
  useEffect(() => {
    if (!editor) return;
    const hasText = !!editor.getText().trim();
    const newIsEmpty = !hasText && attachments.length === 0;
    if (newIsEmpty !== prevIsEmptyRef.current) {
      prevIsEmptyRef.current = newIsEmpty;
      callbackRefs.current.onEmptyChange?.(newIsEmpty);
    }
  }, [attachments, editor]);

  // Restore attachments from draft on mount
  useEffect(() => {
    setAttachments(draft.restoredAttachments);
    // Only run on mount / session change
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [draft.restoredAttachments]);

  const submit = useCallback(() => {
    if (!editor) return;
    if (disabled || submitDisabled) return;

    const content = draft.getContent(attachments);
    if (isContentEmpty(content)) return;

    const text = editor.getText().trim();

    promptRecallDraftRef.current = null;

    const doClear = () => {
      if (!clearOnSubmit) return;
      editor.commands.clearContent();
      prevBashModeRef.current = false;
      pasteCountRef.current = 0;
      setAttachments([]);
      draft.clearDraft();
    };

    if (enableBashMode && isBashModeText(text)) {
      // Bash mode requires immediate execution, can't be queued.
      // Intentionally bypasses onBeforeSubmit — bash commands run inline and
      // cannot be deferred the way normal prompts can.
      if (isLoading) {
        toast.error("Cannot run shell commands while agent is generating");
        return;
      }
      const command = extractBashCommand(text);
      if (command) callbackRefs.current.onBashCommand?.(command);
    } else {
      const serialized = contentToXml(content);

      if (callbackRefs.current.onBeforeSubmit) {
        if (!callbackRefs.current.onBeforeSubmit(serialized, doClear)) {
          return;
        }
      }

      // Normal prompts can be queued when loading
      callbackRefs.current.onSubmit?.(serialized);
    }

    doClear();
  }, [
    editor,
    disabled,
    submitDisabled,
    isLoading,
    draft,
    clearOnSubmit,
    attachments,
    enableBashMode,
  ]);

  submitRef.current = submit;

  const focus = useCallback(() => {
    if (editor?.view) {
      // scrollIntoView:false keeps a focus request from yanking the viewport
      // when the composer is off-screen (e.g. embedded in a command-center cell).
      editor.commands.focus("end", { scrollIntoView: false });
    }
  }, [editor]);
  const blur = useCallback(() => editor?.commands.blur(), [editor]);
  const clear = useCallback(() => {
    editor?.commands.clearContent();
    prevBashModeRef.current = false;
    setAttachments([]);
    draft.clearDraft();
  }, [editor, draft]);
  const getText = useCallback(() => editor?.getText() ?? "", [editor]);
  const setContent = useCallback(
    (content: string | EditorContent) => {
      if (!editor) return;
      editor.commands.setContent(
        typeof content === "string"
          ? content
          : editorContentToTiptapJson(content),
      );
      if (typeof content !== "string") {
        setAttachments(content.attachments ?? []);
      }
      editor.commands.focus("end", { scrollIntoView: false });
      draft.saveDraft(
        editor,
        typeof content === "string" ? attachments : (content.attachments ?? []),
      );
    },
    [editor, draft, attachments],
  );
  const insertEditorContent = useCallback(
    (content: EditorContent) => {
      if (!editor) return;
      editor.commands.focus("end");
      // Paragraphs, not the doc wrapper, so it appends rather than replaces.
      editor.commands.insertContent(
        editorContentToTiptapJson(content).content ?? [],
      );
      draft.saveDraft(editor, attachments);
    },
    [editor, draft, attachments],
  );
  const insertChip = useCallback(
    (chip: MentionChip) => {
      if (!editor) return;
      editor.commands.insertMentionChip({
        type: chip.type,
        id: chip.id,
        label: chip.label,
        pastedText: false,
        chipId: chip.chipId,
        skillPath: chip.skillPath,
        skillSource: chip.skillSource,
        skillName: chip.skillName,
      });
      draft.saveDraft(editor, attachments);
    },
    [editor, draft, attachments],
  );

  const removeChipById = useCallback(
    (chipId: string) => {
      if (!editor) return;
      editor.commands.removeMentionChipById(chipId);
      draft.saveDraft(editor, attachments);
    },
    [editor, draft, attachments],
  );

  const replaceChipAttrs = useCallback(
    (
      chipId: string,
      attrs: Partial<{
        id: string;
        label: string;
        type: MentionChip["type"];
      }>,
    ) => {
      if (!editor) return;
      editor.commands.replaceMentionChipById(chipId, attrs);
      draft.saveDraft(editor, attachments);
    },
    [editor, draft, attachments],
  );

  const addAttachment = useCallback((attachment: FileAttachment) => {
    setAttachments((prev) => {
      if (prev.some((a) => a.id === attachment.id)) return prev;
      return [...prev, attachment];
    });
  }, []);

  const removeAttachment = useCallback((id: string) => {
    setAttachments((prev) => prev.filter((a) => a.id !== id));
  }, []);

  const isEmpty = !editor || (isEmptyState && attachments.length === 0);
  const isBashMode =
    enableBashMode && (editor ? isBashModeText(editor.getText()) : false);

  return {
    editor,
    isReady,
    isEmpty,
    isBashMode,
    submit,
    focus,
    blur,
    clear,
    getText,
    getContent: draft.getContent,
    setContent,
    insertEditorContent,
    insertChip,
    removeChipById,
    replaceChipAttrs,
    attachments,
    addAttachment,
    removeAttachment,
  };
}
