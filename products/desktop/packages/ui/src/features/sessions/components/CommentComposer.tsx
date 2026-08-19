import { PaperPlaneRightIcon, XIcon } from "@phosphor-icons/react";
import { InputGroupAddon, InputGroupButton } from "@posthog/quill";
import type { UserBasic } from "@posthog/shared/domain-types";
import { MentionComposer } from "@posthog/ui/features/canvas/components/MentionComposer";
import { useMentionsDisabledReason } from "@posthog/ui/features/sessions/mentionAvailability";
import { mentionIdsFromContent } from "./commentMentions";

export function CommentComposer({
  value,
  onValueChange,
  onSubmit,
  onCancel,
  members,
  placeholder,
  rows = 3,
  disabled = false,
  submitLabel = "Comment",
  autoFocus = false,
}: {
  value: string;
  onValueChange: (value: string) => void;
  onSubmit: (content: string, mentions: number[]) => void | Promise<void>;
  onCancel?: () => void;
  members: UserBasic[];
  placeholder: string;
  rows?: number;
  disabled?: boolean;
  submitLabel?: string;
  /** For a composer the user just opened, so they can type straight away. */
  autoFocus?: boolean;
}) {
  const mentionsDisabledReason = useMentionsDisabledReason();
  const mentionMembers = mentionsDisabledReason ? [] : members;
  const showMentionsDisabled = !!mentionsDisabledReason && value.includes("@");
  const submit = () => {
    const content = value.trim();
    if (!content || disabled) return;
    void Promise.resolve(
      onSubmit(content, mentionIdsFromContent(content, mentionMembers)),
    ).catch(() => undefined);
  };

  return (
    <MentionComposer
      value={value}
      onValueChange={onValueChange}
      onSubmit={submit}
      members={mentionMembers}
      autoFocus={autoFocus}
      placeholder={placeholder}
      rows={rows}
      inputClassName="max-h-40 text-[13px]"
    >
      <InputGroupAddon align="block-end" className="p-1">
        {showMentionsDisabled && (
          <output className="px-1 text-muted-foreground text-xs">
            {mentionsDisabledReason}
          </output>
        )}
        {onCancel && (
          <InputGroupButton
            size="icon-sm"
            aria-label="Cancel"
            onClick={onCancel}
          >
            <XIcon />
          </InputGroupButton>
        )}
        <span className="ml-auto">
          <InputGroupButton
            variant="primary"
            size="icon-sm"
            aria-label={submitLabel}
            disabled={!value.trim() || disabled}
            loading={disabled}
            onClick={submit}
          >
            <PaperPlaneRightIcon />
          </InputGroupButton>
        </span>
      </InputGroupAddon>
    </MentionComposer>
  );
}
