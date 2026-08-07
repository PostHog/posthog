import { Text } from "@radix-ui/themes";
import type { ReactNode } from "react";

interface InboxCardTitleProps {
  children: ReactNode;
}

export function InboxCardTitle({ children }: InboxCardTitleProps) {
  return (
    <Text
      as="span"
      className="min-w-0 flex-1 break-words font-semibold text-[14px] text-gray-11 leading-snug tracking-tight"
      style={{ fontFamily: "var(--heading-font-family, var(--font-sans))" }}
    >
      {children}
    </Text>
  );
}
