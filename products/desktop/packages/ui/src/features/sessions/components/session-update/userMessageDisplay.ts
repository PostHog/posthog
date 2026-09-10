import {
  type InjectedBlock,
  splitInjectedBlocks,
} from "@posthog/core/editor/injectedBlocks";
import {
  extractPeerAgentMessage,
  type PeerAgentMessage,
} from "./peerAgentMessage";
import { collapsePiSkillInvocation } from "./piSkillInvocation";

export interface UserMessageParts {
  peerAgentMessage: PeerAgentMessage | null;
  blocks: InjectedBlock[];
  displayContent: string;
}

export function splitUserMessage(content: string): UserMessageParts {
  const peerAgentMessage = extractPeerAgentMessage(content);
  const { blocks, text } = splitInjectedBlocks(
    peerAgentMessage ? peerAgentMessage.body : content,
  );
  return {
    peerAgentMessage,
    blocks,
    displayContent: collapsePiSkillInvocation(text),
  };
}

export function userMessageDisplayText(content: string): string {
  return splitUserMessage(content).displayContent;
}
