import { ArrowUp, StopCircle } from "@phosphor-icons/react";
import {
  InputGroup,
  InputGroupAddon,
  InputGroupButton,
  InputGroupTextarea,
} from "@posthog/quill";
import type { AcpMessage } from "@posthog/shared";
import { ThreadView } from "@posthog/ui/features/sessions/components/ThreadView";
import { Flex, Text, Tooltip } from "@radix-ui/themes";
import {
  type KeyboardEvent,
  type ReactNode,
  useEffect,
  useRef,
  useState,
} from "react";

/**
 * The conversation + composer half of a deployed-agent chat, shared by the
 * per-agent chat pane and the agent builder dock. Renders the live ACP messages
 * through the native `ConversationView` (collapse disabled so the agent's prose
 * shows inline) and an auto-growing composer with Enter-to-send / Cancel that
 * mirrors the main task chat's input shell.
 */
export function AgentChatSurface({
  messages,
  isStreaming,
  error,
  emptyHint,
  emptyState,
  aboveComposer,
  belowConversation,
  composerDisabledReason,
  scrollX = true,
  placeholder = "Message this agent…",
  draft,
  onSend,
  onCancel,
}: {
  messages: AcpMessage[];
  isStreaming: boolean;
  error: string | null;
  emptyHint: string;
  /** Richer empty-state content (e.g. suggestions); falls back to `emptyHint`. */
  emptyState?: ReactNode;
  /** Optional content rendered between the transcript and the composer. */
  aboveComposer?: ReactNode;
  /** Optional content rendered between the transcript and `aboveComposer`,
   * anchored to the conversation rather than the input. */
  belowConversation?: ReactNode;
  /** When set, the composer is disabled and this string is shown as a tooltip
   * on the send button. Use when the chat is parked (e.g. waiting on an
   * inline approval decision). */
  composerDisabledReason?: string;
  /** Allow horizontal scroll of the transcript (false in the narrow dock). */
  scrollX?: boolean;
  /** Composer placeholder. */
  placeholder?: string;
  /** When set, prefills the composer with `text` (without sending). Bump
   * `token` each time a new draft should repopulate the input — the same text
   * re-applies on a fresh token so re-triggering a seeded prompt works. */
  draft?: { text: string; token: number };
  onSend: (text: string) => void;
  onCancel: () => void;
}) {
  return (
    <Flex direction="column" className="min-h-0 flex-1">
      <div className="flex min-h-0 flex-1 flex-col">
        {messages.length === 0 ? (
          (emptyState ?? (
            <div className="flex h-full items-center justify-center px-6 text-center">
              <Text className="max-w-sm text-[13px] text-gray-10 leading-snug">
                {emptyHint}
              </Text>
            </div>
          ))
        ) : (
          <ThreadView
            events={messages}
            isPromptPending={isStreaming}
            collapseMode="none"
            scrollX={scrollX}
          />
        )}
      </div>
      {belowConversation}
      {error ? (
        <Text className="shrink-0 px-4 pb-1 text-(--red-11) text-[12px]">
          {error}
        </Text>
      ) : null}
      {aboveComposer}
      <Composer
        isStreaming={isStreaming}
        placeholder={placeholder}
        disabledReason={composerDisabledReason}
        draft={draft}
        onSend={onSend}
        onCancel={onCancel}
      />
    </Flex>
  );
}

function Composer({
  isStreaming,
  placeholder,
  disabledReason,
  draft,
  onSend,
  onCancel,
}: {
  isStreaming: boolean;
  placeholder: string;
  disabledReason?: string;
  draft?: { text: string; token: number };
  onSend: (text: string) => void;
  onCancel: () => void;
}) {
  const [text, setText] = useState("");
  const parked = !!disabledReason;
  const textareaRef = useRef<HTMLTextAreaElement>(null);

  // Prefill (but don't send) when a new draft lands — a seeded prompt drops into
  // the composer for the user to review, edit, and send. Keyed on `token` so the
  // same prompt re-applies on a fresh trigger. Never clobber text the user has
  // already typed but not sent: if the composer is non-empty, leave it as-is
  // (still focusing it) so a seeded prompt is genuinely non-destructive.
  const lastDraftToken = useRef<number | null>(null);
  useEffect(() => {
    if (!draft || draft.token === lastDraftToken.current) return;
    lastDraftToken.current = draft.token;
    setText((current) => (current.trim() ? current : draft.text));
    textareaRef.current?.focus();
  }, [draft]);

  function submit() {
    if (parked) return;
    const trimmed = text.trim();
    if (!trimmed) return;
    onSend(trimmed);
    setText("");
  }
  function onKeyDown(e: KeyboardEvent) {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      submit();
    }
  }

  const submitBlocked = parked || !text.trim();
  const sendTooltip = parked
    ? (disabledReason as string)
    : submitBlocked
      ? "Enter a message"
      : "Send message";

  return (
    <div className="shrink-0 px-3 pt-2 pb-3">
      <InputGroup className="h-auto cursor-text bg-card focus-within:ring-1 focus-within:ring-purple-9">
        <InputGroupTextarea
          ref={textareaRef}
          value={text}
          onChange={(e) => setText(e.target.value)}
          onKeyDown={onKeyDown}
          placeholder={parked ? (disabledReason as string) : placeholder}
          rows={1}
          disabled={parked}
          className="max-h-[160px] min-h-[40px] resize-none text-[14px] [field-sizing:content]"
        />
        <InputGroupAddon align="block-end" className="p-1">
          <span className="ml-auto flex items-center gap-1">
            {isStreaming ? (
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
            ) : (
              <Tooltip content={sendTooltip}>
                <InputGroupButton
                  variant="primary"
                  size="icon-sm"
                  onClick={submit}
                  disabled={submitBlocked}
                  aria-label="Send message"
                >
                  <ArrowUp size={14} weight="bold" />
                </InputGroupButton>
              </Tooltip>
            )}
          </span>
        </InputGroupAddon>
      </InputGroup>
    </div>
  );
}
