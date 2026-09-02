import type { ReactNode } from "react";

interface InboxCardTitleProps {
  /**
   * Conventional-commit scope tag, rendered as an inline prefix to the title
   * text (not a flex sibling), so it stays on the title's first line and the
   * title wraps beneath it instead of centering vertically beside the tag.
   */
  tag?: ReactNode;
  children: ReactNode;
}

export function InboxCardTitle({ tag, children }: InboxCardTitleProps) {
  return (
    <span
      className="min-w-0 break-words font-semibold text-[14px] text-gray-11 leading-snug tracking-tight"
      style={{ fontFamily: "var(--heading-font-family, var(--font-sans))" }}
    >
      {tag}
      {children}
    </span>
  );
}
