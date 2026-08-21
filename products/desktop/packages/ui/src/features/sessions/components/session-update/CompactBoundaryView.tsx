import { ChatMarker, ChatMarkerContent } from "@posthog/quill";
import type { CompactBoundaryMetadata } from "@posthog/ui/features/sessions/types";

interface CompactBoundaryDisplayMetadata {
  trigger?: "manual" | "auto";
  tokensK?: number;
  percent?: number;
}

function getCompactBoundaryMetadata({
  trigger,
  preTokens,
  contextSize,
}: CompactBoundaryMetadata): CompactBoundaryDisplayMetadata {
  const metadata: CompactBoundaryDisplayMetadata = {
    trigger,
  };

  if (preTokens === undefined) {
    return metadata;
  }

  metadata.tokensK = Math.round(preTokens / 1000);
  if (contextSize) {
    metadata.percent = Math.round((preTokens / contextSize) * 100);
  }

  return metadata;
}

export function formatCompactBoundaryLabel(
  props: CompactBoundaryMetadata,
): string {
  const metadata = getCompactBoundaryMetadata(props);
  const details: string[] = [];
  if (metadata.trigger) {
    details.push(metadata.trigger);
  }
  if (metadata.percent !== undefined) {
    details.push(`${metadata.percent}% of context`);
  } else if (metadata.tokensK !== undefined) {
    details.push(`~${metadata.tokensK}K tokens`);
  }
  return ["Conversation compacted", ...details].join(" · ");
}

export function CompactBoundaryView({
  trigger,
  preTokens,
  contextSize,
}: CompactBoundaryMetadata) {
  return (
    <ChatMarker variant="separator">
      <ChatMarkerContent>
        {formatCompactBoundaryLabel({ trigger, preTokens, contextSize })}
      </ChatMarkerContent>
    </ChatMarker>
  );
}
