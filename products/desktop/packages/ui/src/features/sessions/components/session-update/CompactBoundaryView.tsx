import { Lightning } from "@phosphor-icons/react";
import { ChatMarker, ChatMarkerContent } from "@posthog/quill";
import type { CompactBoundaryMetadata } from "@posthog/ui/features/sessions/types";
import { Badge, Box, Flex, Text } from "@radix-ui/themes";
import { useChatThreadChrome } from "../chat-thread/chatThreadChrome";

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

export function formatLegacyCompactBoundaryDetails(
  props: CompactBoundaryMetadata,
): string | null {
  const metadata = getCompactBoundaryMetadata(props);
  if (metadata.tokensK === undefined) return null;
  if (metadata.percent !== undefined) {
    return `${metadata.percent}% of context · ~${metadata.tokensK}K tokens summarized`;
  }
  return `~${metadata.tokensK}K tokens summarized`;
}

export function CompactBoundaryView({
  trigger,
  preTokens,
  contextSize,
}: CompactBoundaryMetadata) {
  const metadata = getCompactBoundaryMetadata({
    trigger,
    preTokens,
    contextSize,
  });
  const legacyDetails = formatLegacyCompactBoundaryDetails({
    trigger,
    preTokens,
    contextSize,
  });
  // New thread renders the boundary as a centered separator marker; the legacy thread keeps its
  // bordered badge row so ConversationView is unchanged when the chat thread is off.
  const chatChrome = useChatThreadChrome();

  if (chatChrome) {
    return (
      <ChatMarker variant="separator">
        <ChatMarkerContent>
          {formatCompactBoundaryLabel({ trigger, preTokens, contextSize })}
        </ChatMarkerContent>
      </ChatMarker>
    );
  }

  return (
    <Box className="my-1 border-blue-6 border-l-2 py-1 pl-3 dark:border-blue-8">
      <Flex align="center" gap="2">
        <Lightning size={14} weight="fill" className="text-blue-9" />
        <Text className="text-[13px] text-gray-11">Conversation compacted</Text>
        {metadata.trigger && (
          <Badge
            size="1"
            color={metadata.trigger === "auto" ? "orange" : "blue"}
            variant="soft"
          >
            {metadata.trigger}
          </Badge>
        )}
        {legacyDetails && (
          <Text className="text-[13px] text-gray-9">({legacyDetails})</Text>
        )}
      </Flex>
    </Box>
  );
}
