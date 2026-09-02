import type { ContentBlock } from "@agentclientprotocol/sdk";
import { describe, expect, it } from "vitest";
import { SKILL_BUTTON_CATALOG } from "./catalog";
import { buildSkillButtonPromptBlocks, extractSkillButtonId } from "./prompts";

describe("buildSkillButtonPromptBlocks", () => {
  it("produces a text block carrying the button id under posthogCode meta", () => {
    const [block] = buildSkillButtonPromptBlocks("add-analytics");
    expect(block.type).toBe("text");
    expect((block as { text: string }).text).toBe(
      SKILL_BUTTON_CATALOG["add-analytics"].prompt,
    );
    expect((block as { _meta?: unknown })._meta).toEqual({
      posthogCode: { skillButtonId: "add-analytics" },
    });
  });
});

describe("extractSkillButtonId", () => {
  it("round-trips through buildSkillButtonPromptBlocks", () => {
    for (const id of Object.keys(SKILL_BUTTON_CATALOG)) {
      const blocks = buildSkillButtonPromptBlocks(
        id as keyof typeof SKILL_BUTTON_CATALOG,
      );
      expect(extractSkillButtonId(blocks)).toBe(id);
    }
  });

  it("returns null for blocks with no meta", () => {
    const blocks: ContentBlock[] = [{ type: "text", text: "hello" }];
    expect(extractSkillButtonId(blocks)).toBeNull();
  });

  it("returns null when meta carries an unknown id", () => {
    const blocks: ContentBlock[] = [
      {
        type: "text",
        text: "hi",
        _meta: { posthogCode: { skillButtonId: "unknown" } },
      },
    ];
    expect(extractSkillButtonId(blocks)).toBeNull();
  });

  it("ignores plain text that happens to match a prompt string", () => {
    const blocks: ContentBlock[] = [
      { type: "text", text: SKILL_BUTTON_CATALOG["add-analytics"].prompt },
    ];
    expect(extractSkillButtonId(blocks)).toBeNull();
  });

  it("handles undefined blocks", () => {
    expect(extractSkillButtonId(undefined)).toBeNull();
    expect(extractSkillButtonId([])).toBeNull();
  });
});
