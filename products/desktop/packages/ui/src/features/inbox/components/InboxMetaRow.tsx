import { cn } from "@posthog/quill";
import { Flex } from "@radix-ui/themes";
import type { ReactNode } from "react";

const META_ROW_CLASS =
  "cursor-default select-none text-[12px] text-gray-10 leading-none";

interface InboxMetaRowProps {
  children: ReactNode;
  className?: string;
}

export function InboxMetaRow({ children, className }: InboxMetaRowProps) {
  return (
    <Flex
      align="center"
      gap="2"
      wrap="wrap"
      className={cn(META_ROW_CLASS, className)}
    >
      {children}
    </Flex>
  );
}

export function InboxMetaSeparator() {
  return (
    <span
      className="shrink-0 select-none px-0.5 text-(--gray-9) text-[13px] leading-none"
      aria-hidden
    >
      ·
    </span>
  );
}

interface InboxMetaTextProps {
  children: ReactNode;
  className?: string;
  mono?: boolean;
}

export function InboxMetaText({
  children,
  className,
  mono = false,
}: InboxMetaTextProps) {
  return (
    <span
      className={cn(
        META_ROW_CLASS,
        mono && "font-mono tabular-nums",
        className,
      )}
    >
      {children}
    </span>
  );
}
