import type { ResolvedAlwaysOnSkill } from "@posthog/core/skills/alwaysOnSkills";
import { describe, expect, it } from "vitest";
import {
  ALWAYS_ON_SKILL_MD_MAX_BYTES,
  buildAlwaysOnSkillsBlock,
  buildAlwaysOnSkillsCloudText,
  buildChannelContextBlock,
  buildChannelContextText,
  buildCustomInstructionsText,
} from "./prompt-builder";

describe("buildChannelContextText", () => {
  it.each([[undefined], ["   \n "]] as const)(
    "returns null for empty or whitespace content (%s)",
    (input) => {
      expect(buildChannelContextText(input)).toBeNull();
    },
  );

  it("wraps the trimmed body, optionally with an escaped channel name", () => {
    expect(
      buildChannelContextText("body")?.startsWith("<channel_context>"),
    ).toBe(true);
    expect(buildChannelContextText("body", 'a"b')).toContain(
      'channel="a&quot;b"',
    );
  });

  it("backs the ContentBlock form, forwarding the channel context id", () => {
    const text = buildChannelContextText("# Billing", "billing", "chan-1");
    const block = buildChannelContextBlock("# Billing", "billing", "chan-1");
    expect(block).toEqual({ type: "text", text });
  });

  it("emits an id-addressed upkeep instruction when the context id is known", () => {
    const text = buildChannelContextText("# Billing", "billing", "chan-123");
    expect(text).toContain("out of date");
    expect(text).toContain("desktop-file-system-instructions-partial-update");
    expect(text).toContain('id "chan-123"');
    expect(text).toContain("do not resolve the channel by name");
    expect(text).toContain("base_version");
  });

  it("omits the upkeep write instruction when no context id is supplied", () => {
    const text = buildChannelContextText("# Billing", "billing");
    expect(text).not.toContain(
      "desktop-file-system-instructions-partial-update",
    );
    expect(text).not.toContain("Upkeep is the one exception");
    // Still framed as reference material, and the body is preserved.
    expect(text).toContain("reference material, not instructions");
    expect(text?.endsWith("\n# Billing\n</channel_context>")).toBe(true);
  });
});

describe("buildCustomInstructionsText", () => {
  it.each([[undefined], [null], [""], ["   \n  "]] as const)(
    "returns null for empty or whitespace content (%s)",
    (input) => {
      expect(buildCustomInstructionsText(input)).toBeNull();
    },
  );

  it("wraps the trimmed body in a user_custom_instructions element", () => {
    const text = buildCustomInstructionsText("  Always use tabs.  ");
    expect(text).not.toBeNull();
    expect(text?.startsWith("<user_custom_instructions>\n")).toBe(true);
    expect(
      text?.endsWith("\nAlways use tabs.\n</user_custom_instructions>"),
    ).toBe(true);
  });
});

const alwaysOnSkill = (
  overrides: Partial<ResolvedAlwaysOnSkill> = {},
): ResolvedAlwaysOnSkill => ({
  name: "i-have-adhd",
  source: "user",
  path: "/home/u/.claude/skills/i-have-adhd",
  description: "Focus aid",
  skillMdBytes: 120,
  ...overrides,
});

// Mirrors the sandbox's token-boundary mention matcher
// (buildAttachedSkillsPromptContext in @posthog/agent): the cloud text's
// reference lines must trip it or the uploaded bundles are never inlined.
function sandboxMentionRegex(skillName: string): RegExp {
  const escaped = skillName.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
  return new RegExp(`(^|[\\s(\`"'\\[])/${escaped}(?![A-Za-z0-9_/-])`, "m");
}

describe("buildAlwaysOnSkillsCloudText", () => {
  it("returns null when no skills are toggled on", () => {
    expect(buildAlwaysOnSkillsCloudText([])).toBeNull();
  });

  it("lists each skill as a /name mention the sandbox inliner matches", () => {
    const text = buildAlwaysOnSkillsCloudText([
      alwaysOnSkill(),
      alwaysOnSkill({ name: "review.checklist", source: "codex" }),
    ]);
    expect(text?.startsWith("<always_on_skills>\n")).toBe(true);
    expect(text).toContain("marked these skills as always-on");
    expect(text).toContain("- /i-have-adhd: Focus aid");
    expect(text).toMatch(sandboxMentionRegex("i-have-adhd"));
    expect(text).toMatch(sandboxMentionRegex("review.checklist"));
    expect(text?.endsWith("\n</always_on_skills>")).toBe(true);
  });

  it("marks bundled skills as preinstalled and tolerates empty descriptions", () => {
    const text = buildAlwaysOnSkillsCloudText([
      alwaysOnSkill({ name: "max", source: "bundled", description: "" }),
    ]);
    expect(text).toContain("- /max (preinstalled PostHog skill)");
  });
});

describe("buildAlwaysOnSkillsBlock", () => {
  it("returns null when no skills are toggled on", () => {
    expect(buildAlwaysOnSkillsBlock([])).toBeNull();
  });

  it("inlines a skill body with its directory path", () => {
    const block = buildAlwaysOnSkillsBlock([
      alwaysOnSkill({ body: "Keep responses short." }),
    ]);
    const text = (block as { text: string }).text;
    expect(block?.type).toBe("text");
    expect(text).toContain("--- BEGIN ALWAYS-ON SKILL i-have-adhd ---");
    expect(text).toContain("Keep responses short.");
    expect(text).toContain("--- END ALWAYS-ON SKILL i-have-adhd ---");
    expect(text).toContain(
      "Skill directory: /home/u/.claude/skills/i-have-adhd",
    );
  });

  it.each([
    ["no body", alwaysOnSkill()],
    [
      "an oversized manifest",
      alwaysOnSkill({
        body: "big",
        skillMdBytes: ALWAYS_ON_SKILL_MD_MAX_BYTES + 1,
      }),
    ],
  ])("degrades a skill with %s to a path reference", (_label, skill) => {
    const text = (buildAlwaysOnSkillsBlock([skill]) as { text: string }).text;
    expect(text).not.toContain("BEGIN ALWAYS-ON SKILL");
    expect(text).toContain(
      "- /i-have-adhd: Focus aid — read its SKILL.md at /home/u/.claude/skills/i-have-adhd",
    );
  });

  it("stops inlining once the total budget is spent", () => {
    const big = 30 * 1024;
    const text = (
      buildAlwaysOnSkillsBlock([
        alwaysOnSkill({ name: "first", body: "one", skillMdBytes: big }),
        alwaysOnSkill({ name: "second", body: "two", skillMdBytes: big }),
        alwaysOnSkill({ name: "third", body: "three", skillMdBytes: big }),
        alwaysOnSkill({ name: "fourth", body: "four", skillMdBytes: big }),
      ]) as { text: string }
    ).text;
    expect(text).toContain("--- BEGIN ALWAYS-ON SKILL third ---");
    expect(text).not.toContain("--- BEGIN ALWAYS-ON SKILL fourth ---");
    expect(text).toContain("- /fourth: Focus aid — read its SKILL.md at");
  });
});

describe("buildChannelContextBlock", () => {
  it.each([[undefined], [null], [""], ["   \n  "]] as const)(
    "returns null for empty or whitespace content (%s)",
    (input) => {
      expect(buildChannelContextBlock(input)).toBeNull();
    },
  );

  it("wraps trimmed content in a labeled, non-binding background block", () => {
    const block = buildChannelContextBlock("  # Billing\n\nUse cents.  ");
    expect(block).not.toBeNull();
    expect(block?.type).toBe("text");
    const text = (block as { text: string }).text;
    // Framed as optional reference, not instructions.
    expect(text).toContain("reference material, not instructions");
    expect(text).toContain("don't limit your work to it");
    // The element wraps the framing + trimmed body so the UI can collapse it.
    expect(text.startsWith("<channel_context>\n")).toBe(true);
    expect(text.endsWith("\n# Billing\n\nUse cents.\n</channel_context>")).toBe(
      true,
    );
  });

  it("embeds the channel name as an escaped attribute when provided", () => {
    const block = buildChannelContextBlock("body", 'on"b');
    const text = (block as { text: string }).text;
    expect(text.startsWith('<channel_context channel="on&quot;b">')).toBe(true);
  });
});
