import { stripTrailingAttachmentSummary } from "@posthog/core/editor/cloud-prompt";
import {
  type InjectedBlock,
  splitInjectedBlocks,
} from "@posthog/core/editor/injectedBlocks";
import { extractImageFileTags } from "@posthog/core/sessions/promptContent";
import type { UserMessageAttachment } from "@posthog/ui/features/sessions/userMessageTypes";
import { hasFileMentions } from "./parseFileMentions";
import {
  extractPeerAgentMessage,
  type PeerAgentMessage,
} from "./peerAgentMessage";
import { collapsePiSkillInvocation } from "./piSkillInvocation";

export interface UserMessageParts {
  peerAgentMessage: PeerAgentMessage | null;
  blocks: InjectedBlock[];
  displayContent: string;
  attachments: UserMessageAttachment[];
}

export function splitUserMessage(
  content: string,
  attachments: UserMessageAttachment[] = [],
): UserMessageParts {
  const peerAgentMessage = extractPeerAgentMessage(content);
  const { blocks, text } = splitInjectedBlocks(
    peerAgentMessage ? peerAgentMessage.body : content,
  );
  const { text: displayText, attachments: imageAttachments } =
    extractImageFileTags(collapsePiSkillInvocation(text));
  // contentToXml folds every attachment into a <file /> mention, so text that
  // still carries one already lists the message's attachments inline.
  const visibleAttachments = hasFileMentions(displayText)
    ? imageAttachments
    : [
        ...attachments,
        ...imageAttachments.filter(
          (image) => !attachments.some(({ id }) => id === image.id),
        ),
      ];
  return {
    peerAgentMessage,
    blocks,
    // The "Attached files: …" summary only stands in for attachments we cannot draw.
    displayContent:
      visibleAttachments.length > 0
        ? stripTrailingAttachmentSummary(displayText)
        : displayText,
    attachments: visibleAttachments,
  };
}

export function userMessageDisplayText(content: string): string {
  return splitUserMessage(content).displayContent;
}
