import type { ContentBlock } from "@agentclientprotocol/sdk";
import {
  isSkillButtonId,
  SKILL_BUTTON_CATALOG,
  type SkillButtonId,
} from "./catalog";

export const SKILL_BUTTON_META_NAMESPACE = "posthogCode";
export const SKILL_BUTTON_META_FIELD = "skillButtonId";

export function buildSkillButtonPromptBlocks(
  buttonId: SkillButtonId,
): ContentBlock[] {
  return [
    {
      type: "text",
      text: SKILL_BUTTON_CATALOG[buttonId].prompt,
      _meta: {
        [SKILL_BUTTON_META_NAMESPACE]: {
          [SKILL_BUTTON_META_FIELD]: buttonId,
        },
      },
    },
  ];
}

export function extractSkillButtonId(
  blocks: ContentBlock[] | undefined,
): SkillButtonId | null {
  if (!blocks?.length) return null;
  for (const block of blocks) {
    const meta = (block as { _meta?: Record<string, unknown> })._meta;
    const namespace = meta?.[SKILL_BUTTON_META_NAMESPACE] as
      | Record<string, unknown>
      | undefined;
    const id = namespace?.[SKILL_BUTTON_META_FIELD];
    if (isSkillButtonId(id)) {
      return id;
    }
  }
  return null;
}
