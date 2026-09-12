import {
  type InjectedBlock,
  splitInjectedBlocks,
} from "@posthog/core/editor/injectedBlocks";
import { resolveMessageAttachments } from "@posthog/core/sessions/promptContent";
import type { UserMessageAttachment } from "@posthog/ui/features/sessions/userMessageTypes";
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
  const resolved = resolveMessageAttachments(
    collapsePiSkillInvocation(text),
    attachments,
  );
  return {
    peerAgentMessage,
    blocks,
    displayContent: resolved.text,
    attachments: resolved.attachments,
  };
}

export function userMessageDisplayText(content: string): string {
  return splitUserMessage(content).displayContent;
}
