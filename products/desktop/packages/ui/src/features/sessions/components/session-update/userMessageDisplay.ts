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

// Every surface that shows a user message reads it through here: the bubble
// puts each block behind a chip, and surfaces that only label a message take
// `displayContent`. A message relayed from another agent run carries the
// sender's body inside a provenance envelope, so that unwraps first.
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

/** Just the text, for surfaces that label a message instead of rendering it. */
export function userMessageDisplayText(content: string): string {
  return splitUserMessage(content).displayContent;
}
