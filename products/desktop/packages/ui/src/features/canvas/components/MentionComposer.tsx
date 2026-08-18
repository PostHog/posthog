import { RobotIcon } from "@phosphor-icons/react";
import { Avatar, AvatarFallback, InputGroup } from "@posthog/quill";
import type { UserBasic } from "@posthog/shared/domain-types";
import { UserAvatar } from "@posthog/ui/features/auth/UserAvatar";
import { useCommentEmojiList } from "@posthog/ui/features/canvas/components/CommentEmojiProvider";
import {
  type EmojiSuggestion,
  filterEmojiSuggestions,
} from "@posthog/ui/features/canvas/utils/emojiSuggestions";
import {
  type ComposerMentionCandidate,
  contentToDoc,
  docToContent,
  filterComposerMentionCandidates,
} from "@posthog/ui/features/canvas/utils/mentionComposer";
import { userDisplayName } from "@posthog/ui/features/canvas/utils/userDisplay";
import { Extension } from "@tiptap/core";
import Mention, { type MentionNodeAttrs } from "@tiptap/extension-mention";
import Placeholder from "@tiptap/extension-placeholder";
import { PluginKey } from "@tiptap/pm/state";
import { EditorContent, useEditor } from "@tiptap/react";
import StarterKit from "@tiptap/starter-kit";
import Suggestion from "@tiptap/suggestion";
import { type ReactNode, useEffect, useRef, useState } from "react";
import { EmojiSuggestionGrid } from "./EmojiSuggestionGrid";
import "./mention-chip.css";
import "./mention-composer.css";

interface MentionComposerProps {
  value: string;
  onValueChange: (value: string) => void;
  /** Fired on Enter (without Shift) while the suggestion popup is closed. */
  onSubmit: () => void;
  /** The taggable pool; typically the org's members. */
  members: UserBasic[];
  allowAgentMention?: boolean;
  onMentionInsert?: (member: UserBasic) => void;
  placeholder?: string;
  rows?: number;
  inputClassName?: string;
  /** Put the caret in the editor on mount, for a composer the user just opened. */
  autoFocus?: boolean;
  /** Rendered inside the input group after the editor (send button etc.). */
  children?: ReactNode;
}

/** Styled like the chips MentionText renders on sent messages. */
const MENTION_CHIP_CLASS = "mention-chip";

// Padding lives on the editable element (not the input-group control) so a
// click anywhere in the box focuses the editor.
const EDITOR_CLASS =
  "w-full px-2.5 py-2 outline-none break-words [overflow-wrap:break-word] [white-space:pre-wrap] [word-break:break-word]";

interface SuggestionSession {
  items: ComposerMentionCandidate[];
  command: (candidate: ComposerMentionCandidate) => void;
}

interface EmojiSuggestionSession {
  items: EmojiSuggestion[];
  command: (candidate: EmojiSuggestion) => void;
}

const EMOJI_SUGGESTION_PLUGIN_KEY = new PluginKey("commentEmojiSuggestion");

/**
 * The thread composer: a rich text area that opens an @-mention typeahead over
 * the org's members. Selecting a member inserts an inline chip — rendered the
 * same way as in sent messages — that serializes to the `@posthog/shared`
 * mention token and notifies them in the Activity page.
 */
export function MentionComposer({
  value,
  onValueChange,
  onSubmit,
  members,
  autoFocus = false,
  allowAgentMention = false,
  onMentionInsert,
  placeholder,
  rows,
  inputClassName,
  children,
}: MentionComposerProps) {
  const itemRefs = useRef<(HTMLButtonElement | null)[]>([]);
  const emojiItemRefs = useRef<(HTMLElement | null)[]>([]);
  const [session, setSession] = useState<SuggestionSession | null>(null);
  const [emojiSession, setEmojiSession] =
    useState<EmojiSuggestionSession | null>(null);
  const [selectedIndex, setSelectedIndex] = useState(0);
  const [selectedEmojiIndex, setSelectedEmojiIndex] = useState(0);
  // Esc hides the popup until the current trigger exits; a new trigger re-arms it.
  const [dismissed, setDismissed] = useState(false);
  const [emojiDismissed, setEmojiDismissed] = useState(false);
  const customEmojis = useCommentEmojiList();

  const open = !!session && !dismissed && session.items.length > 0;
  const emojiOpen =
    !!emojiSession && !emojiDismissed && emojiSession.items.length > 0;
  // The list can shrink while a lower row is selected (members filter down).
  const highlightedIndex = Math.min(
    selectedIndex,
    Math.max(0, (session?.items.length ?? 0) - 1),
  );
  const highlightedEmojiIndex = Math.min(
    selectedEmojiIndex,
    Math.max(0, (emojiSession?.items.length ?? 0) - 1),
  );

  // The suggestion plugin's callbacks close over refs so they always see the
  // latest props and popup state.
  const membersRef = useRef(members);
  const customEmojisRef = useRef(customEmojis);
  const allowAgentMentionRef = useRef(allowAgentMention);
  const onValueChangeRef = useRef(onValueChange);
  const onSubmitRef = useRef(onSubmit);
  const onMentionInsertRef = useRef(onMentionInsert);
  const openRef = useRef(open);
  const emojiOpenRef = useRef(emojiOpen);
  const sessionRef = useRef(session);
  const emojiSessionRef = useRef(emojiSession);
  const highlightedRef = useRef(highlightedIndex);
  const highlightedEmojiRef = useRef(highlightedEmojiIndex);
  const lastValueRef = useRef(value);

  useEffect(() => {
    membersRef.current = members;
    customEmojisRef.current = customEmojis;
    allowAgentMentionRef.current = allowAgentMention;
    onValueChangeRef.current = onValueChange;
    onSubmitRef.current = onSubmit;
    onMentionInsertRef.current = onMentionInsert;
    openRef.current = open;
    emojiOpenRef.current = emojiOpen;
    sessionRef.current = session;
    emojiSessionRef.current = emojiSession;
    highlightedRef.current = highlightedIndex;
    highlightedEmojiRef.current = highlightedEmojiIndex;
  }, [
    allowAgentMention,
    customEmojis,
    emojiOpen,
    emojiSession,
    highlightedEmojiIndex,
    highlightedIndex,
    members,
    onMentionInsert,
    onSubmit,
    onValueChange,
    open,
    session,
  ]);

  const editor = useEditor(
    {
      autofocus: autoFocus ? "end" : false,
      extensions: [
        StarterKit.configure({
          heading: false,
          blockquote: false,
          codeBlock: false,
          bulletList: false,
          orderedList: false,
          listItem: false,
          horizontalRule: false,
          bold: false,
          italic: false,
          strike: false,
          code: false,
          link: false,
        }),
        Placeholder.configure({ placeholder: placeholder ?? "" }),
        Extension.create({
          name: "commentEmojiSuggestion",
          addProseMirrorPlugins() {
            return [
              Suggestion({
                pluginKey: EMOJI_SUGGESTION_PLUGIN_KEY,
                editor: this.editor,
                char: ":",
                startOfLine: false,
                allowSpaces: false,
                allow: ({ state, range }) => {
                  const before = state.doc.textBetween(
                    Math.max(0, range.from - 1),
                    range.from,
                  );
                  return before === "" || /\s/.test(before);
                },
                items: ({ query }) =>
                  filterEmojiSuggestions(query, customEmojisRef.current),
                command: ({ editor: e, range, props }) => {
                  const emoji = props as unknown as EmojiSuggestion;
                  e.chain()
                    .focus()
                    .insertContentAt(range, emoji.insertion)
                    .run();
                },
                render: () => ({
                  onStart: (props) => {
                    setEmojiDismissed(false);
                    setSelectedEmojiIndex(0);
                    setEmojiSession({
                      items: props.items as unknown as EmojiSuggestion[],
                      command: (candidate) =>
                        props.command(
                          candidate as unknown as Record<string, unknown>,
                        ),
                    });
                  },
                  onUpdate: (props) => {
                    setSelectedEmojiIndex(0);
                    setEmojiSession({
                      items: props.items as unknown as EmojiSuggestion[],
                      command: (candidate) =>
                        props.command(
                          candidate as unknown as Record<string, unknown>,
                        ),
                    });
                  },
                  onKeyDown: ({ event }) => {
                    if (event.key === "Escape" && emojiSessionRef.current) {
                      setEmojiDismissed(true);
                      return true;
                    }
                    if (!emojiOpenRef.current) return false;
                    const items = emojiSessionRef.current?.items ?? [];
                    let next: number | null = null;
                    if (event.key === "ArrowRight") {
                      next = highlightedEmojiRef.current + 1;
                    } else if (event.key === "ArrowLeft") {
                      next = highlightedEmojiRef.current - 1;
                    } else if (event.key === "ArrowDown") {
                      next = highlightedEmojiRef.current + 6;
                    } else if (event.key === "ArrowUp") {
                      next = highlightedEmojiRef.current - 6;
                    }
                    if (next !== null) {
                      const bounded = Math.max(
                        0,
                        Math.min(items.length - 1, next),
                      );
                      setSelectedEmojiIndex(bounded);
                      emojiItemRefs.current[bounded]?.scrollIntoView({
                        block: "nearest",
                      });
                      return true;
                    }
                    if (event.key === "Enter" || event.key === "Tab") {
                      const candidate = items[highlightedEmojiRef.current];
                      if (candidate)
                        emojiSessionRef.current?.command(candidate);
                      return true;
                    }
                    return false;
                  },
                  onExit: () => {
                    setEmojiSession(null);
                    setEmojiDismissed(false);
                  },
                }),
              }),
            ];
          },
        }),
        Mention.configure({
          renderHTML: ({ node }) => [
            "span",
            { class: MENTION_CHIP_CLASS, title: node.attrs.id },
            `@${node.attrs.label}`,
          ],
          renderText: ({ node }) => `@${node.attrs.label}`,
          suggestion: {
            char: "@",
            allowSpaces: true,
            items: ({ query }) =>
              filterComposerMentionCandidates(
                membersRef.current,
                query,
                allowAgentMentionRef.current,
              ),
            command: ({ editor: e, range, props }) => {
              const candidate = props as unknown as ComposerMentionCandidate;
              if (candidate.kind === "agent") {
                e.chain()
                  .focus()
                  .insertContentAt(range, { type: "text", text: "@agent " })
                  .run();
                return;
              }
              const { member } = candidate;
              e.chain()
                .focus()
                .insertContentAt(range, [
                  {
                    type: "mention",
                    attrs: { id: member.email, label: userDisplayName(member) },
                  },
                  { type: "text", text: " " },
                ])
                .run();
              onMentionInsertRef.current?.(member);
            },
            render: () => ({
              onStart: (props) => {
                setDismissed(false);
                setSelectedIndex(0);
                setSession({
                  items: props.items as unknown as ComposerMentionCandidate[],
                  command: (candidate) =>
                    props.command(candidate as unknown as MentionNodeAttrs),
                });
              },
              onUpdate: (props) => {
                setSelectedIndex(0);
                setSession({
                  items: props.items as unknown as ComposerMentionCandidate[],
                  command: (candidate) =>
                    props.command(candidate as unknown as MentionNodeAttrs),
                });
              },
              onKeyDown: ({ event }) => {
                if (event.key === "Escape" && sessionRef.current) {
                  setDismissed(true);
                  return true;
                }
                if (!openRef.current) return false;
                const items = sessionRef.current?.items ?? [];
                if (event.key === "ArrowDown" || event.key === "ArrowUp") {
                  const delta =
                    event.key === "ArrowDown" ? 1 : items.length - 1;
                  const next = (highlightedRef.current + delta) % items.length;
                  setSelectedIndex(next);
                  itemRefs.current[next]?.scrollIntoView({ block: "nearest" });
                  return true;
                }
                if (event.key === "Enter" || event.key === "Tab") {
                  const candidate = items[highlightedRef.current];
                  if (candidate) sessionRef.current?.command(candidate);
                  return true;
                }
                return false;
              },
              onExit: () => {
                setSession(null);
                setDismissed(false);
              },
            }),
          },
        }),
      ],
      content: contentToDoc(value),
      editorProps: {
        attributes: {
          class: EDITOR_CLASS,
          ...(rows ? { style: `min-height:${rows * 1.25}rem` } : {}),
        },
        // Runs before the suggestion plugin's handler, so defer to it while
        // the popup is open.
        handleKeyDown: (_view, event) => {
          if (openRef.current || emojiOpenRef.current) return false;
          if (event.key === "Enter" && !event.shiftKey) {
            event.preventDefault();
            onSubmitRef.current();
            return true;
          }
          return false;
        },
      },
      onUpdate: ({ editor: e }) => {
        const text = docToContent(e.state.doc);
        lastValueRef.current = text;
        onValueChangeRef.current(text);
      },
    },
    [placeholder, rows],
  );

  // Adopt external value changes (submit clears the draft; a failed post
  // restores it) without echoing our own edits back into the editor.
  useEffect(() => {
    if (!editor || value === lastValueRef.current) return;
    lastValueRef.current = value;
    editor.commands.setContent(contentToDoc(value));
  }, [editor, value]);

  return (
    <div className="relative">
      {emojiOpen && emojiSession && (
        <EmojiSuggestionGrid
          suggestions={emojiSession.items}
          highlightedIndex={highlightedEmojiIndex}
          onHighlight={setSelectedEmojiIndex}
          onSelect={emojiSession.command}
          registerItem={(index, element) => {
            emojiItemRefs.current[index] = element;
          }}
        />
      )}
      {open && session && (
        <div className="absolute inset-x-0 bottom-full z-50 mb-1 flex flex-col overflow-hidden rounded-md border border-border bg-card text-[13px] text-foreground shadow-lg">
          <div
            role="listbox"
            aria-label="Mention a teammate or agent"
            className="max-h-56 overflow-y-auto py-1"
          >
            {session.items.map((candidate, index) => (
              <button
                type="button"
                role="option"
                aria-selected={index === highlightedIndex}
                key={
                  candidate.kind === "agent" ? "agent" : candidate.member.uuid
                }
                ref={(el) => {
                  itemRefs.current[index] = el;
                }}
                // Keep focus in the editor so insertion lands at the caret.
                onMouseDown={(event) => event.preventDefault()}
                onClick={() => session.command(candidate)}
                onMouseEnter={() => setSelectedIndex(index)}
                className={`flex w-full items-center gap-2 border-none px-2 py-1 text-left ${
                  index === highlightedIndex ? "bg-[var(--accent-a4)]" : ""
                }`}
              >
                {candidate.kind === "agent" ? (
                  <Avatar size="xs" className="shrink-0">
                    <AvatarFallback>
                      <RobotIcon size={12} />
                    </AvatarFallback>
                  </Avatar>
                ) : (
                  <UserAvatar
                    user={candidate.member}
                    size="xs"
                    className="shrink-0"
                  />
                )}
                <span className="truncate font-medium text-xs">
                  {candidate.kind === "agent"
                    ? "Agent"
                    : userDisplayName(candidate.member)}
                </span>
                <span className="ml-auto shrink-0 truncate text-muted-foreground text-xs">
                  {candidate.kind === "agent"
                    ? "Send to agent"
                    : candidate.member.email}
                </span>
              </button>
            ))}
          </div>
        </div>
      )}
      <InputGroup className="h-auto cursor-text bg-card">
        <div
          data-slot="input-group-control"
          className={`quill-input-group__control mention-composer w-full overflow-y-auto p-0 ${inputClassName ?? ""}`}
        >
          <EditorContent editor={editor} />
        </div>
        {children}
      </InputGroup>
    </div>
  );
}
