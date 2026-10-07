import type { ContentBlock } from "@agentclientprotocol/sdk";
import {
  deserializeCloudPrompt,
  promptBlocksToText,
} from "@posthog/agent-contracts";

export { promptBlocksToText };

export function normalizeCloudPromptContent(
  content: string | ContentBlock[],
): ContentBlock[] {
  if (typeof content === "string") {
    return deserializeCloudPrompt(content);
  }
  return content;
}
