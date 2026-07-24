import type { CloudPromptBlock } from "./types";

/**
 * Wire format prefix shared with `packages/shared/src/cloud-prompt.ts`. The
 * backend's `deserializeCloudPrompt` looks for this prefix and decodes the
 * trailing JSON as `{ blocks: ContentBlock[] }`. Plain-text prompts without
 * attachments are sent as strings (no prefix) so chat echoes stay readable.
 */
export const CLOUD_PROMPT_PREFIX = "__twig_cloud_prompt_v1__:";

export function serializeCloudPrompt(blocks: CloudPromptBlock[]): string {
  if (blocks.length === 1 && blocks[0].type === "text") {
    return blocks[0].text.trim();
  }
  return `${CLOUD_PROMPT_PREFIX}${JSON.stringify({ blocks })}`;
}
