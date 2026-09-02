import { cn } from "@posthog/quill";
import {
  DOT_TONE_VAR,
  type DotTone,
} from "@posthog/ui/features/sidebar/components/items/taskStatusVocabulary";
import type { ReactElement } from "react";

const SIZE = 6;

export interface DocRefDotProps {
  tone: DotTone;
  /** Filled while something is live; hollow once it has settled. */
  style: "solid" | "hollow";
  pulse?: boolean;
}

/** The status mark an inline reference carries, in the app's dot vocabulary. */
export function DocRefDot({
  tone,
  style,
  pulse = false,
}: DocRefDotProps): ReactElement {
  const color = DOT_TONE_VAR[tone];
  return (
    <span
      className={cn(
        "doc-ref-dot",
        pulse && "ph-pulse motion-reduce:animate-none",
      )}
      style={{
        width: SIZE,
        height: SIZE,
        backgroundColor: style === "solid" ? color : "transparent",
        boxShadow:
          style === "hollow" ? `inset 0 0 0 1.5px ${color}` : undefined,
      }}
    />
  );
}
