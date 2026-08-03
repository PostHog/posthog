import { describe, expect, it } from "vitest";
import { rewriteLocalSkillCommandPrompt } from "./commands";
import type { EditorAvailableCommand } from "./types";

const commands: EditorAvailableCommand[] = [
  {
    name: "local-test-skill",
    description: "Local user skill",
    localSkill: {
      name: "local-test-skill",
      source: "user",
      path: "/Users/example/.claude/skills/local-test-skill",
    },
  },
];

describe("message editor commands", () => {
  it("rewrites local skill slash commands to skill tags", () => {
    expect(rewriteLocalSkillCommandPrompt("/local-test-skill", commands)).toBe(
      '<skill name="local-test-skill" source="user" path="/Users/example/.claude/skills/local-test-skill" />',
    );
  });

  it("preserves local skill arguments after the skill tag", () => {
    expect(
      rewriteLocalSkillCommandPrompt(
        "/local-test-skill with context",
        commands,
      ),
    ).toBe(
      '<skill name="local-test-skill" source="user" path="/Users/example/.claude/skills/local-test-skill" /> with context',
    );
  });

  it("does not rewrite unknown commands", () => {
    expect(
      rewriteLocalSkillCommandPrompt("/feedback looks good", commands),
    ).toBe(null);
  });
});
