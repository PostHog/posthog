import { extractCanvasInstructions } from "./canvasInstructions";
import { extractChannelContext } from "./channelContext";
import { extractCustomInstructions } from "./customInstructions";
import { extractOnboardingBrief } from "./onboardingBrief";
import { extractPeerAgentMessage } from "./peerAgentMessage";
import { collapsePiSkillInvocation } from "./piSkillInvocation";
import { extractPosthogContext } from "./posthogContext";

// A stored user message can carry blocks folded in at send time that nobody
// typed. Every surface showing the message peels the same blocks in the same
// order from here, so a new block cannot be handled in the bubble yet still leak
// as raw XML through the jump picker or the minimap. The bubble puts each
// extracted block behind its own tag; surfaces that only label a message take
// `displayContent`.
export interface UserMessageParts {
  peerAgentMessage: ReturnType<typeof extractPeerAgentMessage>;
  posthogContext: ReturnType<typeof extractPosthogContext>;
  channelContext: ReturnType<typeof extractChannelContext>;
  canvasInstructions: ReturnType<typeof extractCanvasInstructions>;
  customInstructions: ReturnType<typeof extractCustomInstructions>;
  onboardingBrief: ReturnType<typeof extractOnboardingBrief>;
  /** What the user wrote, with every injected block peeled off. */
  displayContent: string;
}

export function splitUserMessage(content: string): UserMessageParts {
  // A message relayed from another agent run carries the sender's body inside a
  // provenance envelope, so unwrap that before looking for injected blocks.
  const peerAgentMessage = extractPeerAgentMessage(content);
  const baseContent = peerAgentMessage ? peerAgentMessage.body : content;
  const posthogContext = extractPosthogContext(baseContent);
  const afterPosthogContext = posthogContext?.stripped ?? baseContent;
  const channelContext = extractChannelContext(afterPosthogContext);
  const afterChannelContext = channelContext?.stripped ?? afterPosthogContext;
  const canvasInstructions = extractCanvasInstructions(afterChannelContext);
  const afterCanvasInstructions =
    canvasInstructions?.stripped ?? afterChannelContext;
  const customInstructions = extractCustomInstructions(afterCanvasInstructions);
  const afterCustomInstructions =
    customInstructions?.stripped ?? afterCanvasInstructions;
  const onboardingBrief = extractOnboardingBrief(afterCustomInstructions);

  return {
    peerAgentMessage,
    posthogContext,
    channelContext,
    canvasInstructions,
    customInstructions,
    onboardingBrief,
    displayContent: collapsePiSkillInvocation(
      onboardingBrief?.stripped ?? afterCustomInstructions,
    ),
  };
}

/** Just the text, for surfaces that label a message instead of rendering it. */
export function userMessageDisplayText(content: string): string {
  return splitUserMessage(content).displayContent;
}
