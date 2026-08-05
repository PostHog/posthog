import { PaperPlaneRightIcon, XIcon } from "@phosphor-icons/react";
import { InputGroupAddon, InputGroupButton } from "@posthog/quill";
import type { UserBasic } from "@posthog/shared/domain-types";
import { MentionComposer } from "@posthog/ui/features/canvas/components/MentionComposer";
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
  onSubmit: (content: string, mentions: number[]) => void;
  onCancel?: () => void;
  members: UserBasic[];
  placeholder: string;
  rows?: number;
  disabled?: boolean;
  submitLabel?: string;
  /** For a composer the user just opened, so they can type straight away. */
  autoFocus?: boolean;
}) {
  const submit = () => {
    const content = value.trim();
    if (!content || disabled) return;
    onSubmit(content, mentionIdsFromContent(content, members));
  };

  return (
    <MentionComposer
      value={value}
      onValueChange={onValueChange}
      onSubmit={submit}
      members={members}
      autoFocus={autoFocus}
      placeholder={placeholder}
      rows={rows}
      inputClassName="max-h-40 text-[13px]"
    >
      <InputGroupAddon align="block-end" className="p-1">
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
            onClick={submit}
          >
            <PaperPlaneRightIcon />
          </InputGroupButton>
        </span>
      </InputGroupAddon>
    </MentionComposer>
  );
}
