import type { ContentBlock } from "@agentclientprotocol/sdk";

/**
 * Wire format prefix for structured cloud prompts.
 * Text-only prompts are sent as plain strings (no prefix) as an optimization.
 * Multi-block prompts (text + attachments) are serialized as `PREFIX + JSON({ blocks })`.
 */
export const CLOUD_PROMPT_PREFIX = "__twig_cloud_prompt_v1__:";

export function serializeCloudPrompt(blocks: ContentBlock[]): string {
  if (blocks.length === 1 && blocks[0].type === "text") {
    return blocks[0].text.trim();
  }

  return `${CLOUD_PROMPT_PREFIX}${JSON.stringify({ blocks })}`;
}

export function deserializeCloudPrompt(value: string): ContentBlock[] {
  const trimmed = value.trim();
  if (!trimmed) {
    return [];
  }

  if (!trimmed.startsWith(CLOUD_PROMPT_PREFIX)) {
    return [{ type: "text", text: trimmed }];
  }

  try {
    const parsed = JSON.parse(trimmed.slice(CLOUD_PROMPT_PREFIX.length)) as {
      blocks?: ContentBlock[];
    };

    if (Array.isArray(parsed.blocks) && parsed.blocks.length > 0) {
      return parsed.blocks;
    }
  } catch {
    // Fall through to preserve the raw string if the payload is malformed.
  }

  return [{ type: "text", text: trimmed }];
}

export function promptBlocksToText(blocks: ContentBlock[]): string {
  return blocks
    .filter((b): b is ContentBlock & { type: "text" } => b.type === "text")
    .map((block) => block.text)
    .join("")
    .trim();
}
