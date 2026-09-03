import { Text } from "@posthog/quill";
import type { ReactElement, ReactNode } from "react";

export function ExperimentResultNotice({
  tone,
  children,
}: {
  tone: "neutral" | "warning" | "destructive";
  children: ReactNode;
}): ReactElement {
  const toneClass = {
    neutral: "border-border bg-muted text-muted-foreground",
    warning: "border-warning/30 bg-warning/10 text-warning-foreground",
    destructive:
      "border-destructive/30 bg-destructive/10 text-destructive-foreground",
  }[tone];
  return (
    <Text
      size="xs"
      className={`block rounded-md border px-2.5 py-2 leading-snug ${toneClass}`}
    >
      {children}
    </Text>
  );
}
