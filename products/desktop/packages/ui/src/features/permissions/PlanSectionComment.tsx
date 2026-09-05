import { ArrowUp, Trash } from "@phosphor-icons/react";
import {
  InputGroup,
  InputGroupAddon,
  InputGroupButton,
  InputGroupTextarea,
} from "@posthog/quill";
import { useEffect, useRef, useState } from "react";

interface PlanSectionCommentProps {
  initialText?: string;
  onSubmit: (text: string) => void;
  onDismiss: () => void;
}

export function PlanSectionComment({
  initialText,
  onSubmit,
  onDismiss,
}: PlanSectionCommentProps) {
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const [text, setText] = useState(initialText ?? "");

  useEffect(() => {
    textareaRef.current?.focus();
  }, []);

  const submit = () => {
    const value = text.trim();
    if (value) {
      onSubmit(value);
    }
  };

  return (
    <div className="mt-2">
      <InputGroup>
        <InputGroupTextarea
          ref={textareaRef}
          value={text}
          placeholder="Describe what should change"
          onChange={(event) => setText(event.currentTarget.value)}
          onKeyDown={(event) => {
            if (event.key === "Escape") {
              event.preventDefault();
              onDismiss();
            }
            if (event.key === "Enter" && (event.metaKey || event.ctrlKey)) {
              event.preventDefault();
              submit();
            }
          }}
          className="min-h-[48px] resize-none text-[13px]"
        />
        <InputGroupAddon align="block-end">
          <InputGroupButton
            size="icon-sm"
            variant="default"
            onClick={onDismiss}
            aria-label="Discard comment"
          >
            <Trash size={14} />
          </InputGroupButton>
          <InputGroupButton
            className="ml-auto"
            size="icon-sm"
            variant="primary"
            onClick={submit}
            disabled={!text.trim()}
            aria-label="Add comment"
          >
            <ArrowUp size={14} weight="bold" />
          </InputGroupButton>
        </InputGroupAddon>
      </InputGroup>
    </div>
  );
}
