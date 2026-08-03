import type { SkillInfo } from "@posthog/shared";
import { describe, expect, it } from "vitest";
import {
  type AlwaysOnSkillRef,
  isAlwaysOnSkill,
  pruneAlwaysOnSkillRefs,
  resolveAlwaysOnSkills,
  sanitizeAlwaysOnSkillRefs,
  toggleAlwaysOnSkillRef,
} from "./alwaysOnSkills";

const skill = (overrides: Partial<SkillInfo> = {}): SkillInfo => ({
  name: "i-have-adhd",
  description: "Focus aid",
  source: "user",
  path: "/home/u/.claude/skills/i-have-adhd",
  editable: true,
  skillMdBytes: 120,
  ...overrides,
});

describe("toggleAlwaysOnSkillRef", () => {
  it("adds and removes a ref for a toggleable source", () => {
    const added = toggleAlwaysOnSkillRef([], skill(), true);
    expect(added).toEqual([{ name: "i-have-adhd", source: "user" }]);
    expect(isAlwaysOnSkill(added, skill())).toBe(true);

    const removed = toggleAlwaysOnSkillRef(added, skill(), false);
    expect(removed).toEqual([]);
    expect(isAlwaysOnSkill(removed, skill())).toBe(false);
  });

  it("does not duplicate an already-toggled skill", () => {
    const refs: AlwaysOnSkillRef[] = [{ name: "i-have-adhd", source: "user" }];
    expect(toggleAlwaysOnSkillRef(refs, skill(), true)).toHaveLength(1);
  });

  it("ignores repo-source skills", () => {
    expect(toggleAlwaysOnSkillRef([], skill({ source: "repo" }), true)).toEqual(
      [],
    );
  });
});

describe("sanitizeAlwaysOnSkillRefs", () => {
  it.each([[undefined], [null], ["nope"], [42]])(
    "returns an empty list for non-array input (%s)",
    (input) => {
      expect(sanitizeAlwaysOnSkillRefs(input)).toEqual([]);
    },
  );

  it("keeps valid refs and drops malformed, repo, and duplicate entries", () => {
    expect(
      sanitizeAlwaysOnSkillRefs([
        { name: "a", source: "user" },
        { name: "b", source: "repo" },
        { name: "", source: "user" },
        { name: 42, source: "user" },
        { source: "codex" },
        null,
        { name: "a", source: "user" },
        { name: "c", source: "bundled" },
      ]),
    ).toEqual([
      { name: "a", source: "user" },
      { name: "c", source: "bundled" },
    ]);
  });
});

describe("resolveAlwaysOnSkills", () => {
  it("resolves refs against the live list by name and source", () => {
    const resolved = resolveAlwaysOnSkills(
      [{ name: "i-have-adhd", source: "user" }],
      [skill({ path: "/moved/i-have-adhd" })],
    );
    expect(resolved).toEqual([
      {
        name: "i-have-adhd",
        source: "user",
        path: "/moved/i-have-adhd",
        description: "Focus aid",
        skillMdBytes: 120,
      },
    ]);
  });

  it("drops refs with no live match and dedupes repeated refs", () => {
    const resolved = resolveAlwaysOnSkills(
      [
        { name: "gone", source: "user" },
        { name: "i-have-adhd", source: "user" },
        { name: "i-have-adhd", source: "user" },
        // Same name under a different source must not match.
        { name: "i-have-adhd", source: "codex" },
      ],
      [skill()],
    );
    expect(resolved).toHaveLength(1);
    expect(resolved[0].name).toBe("i-have-adhd");
  });
});

describe("pruneAlwaysOnSkillRefs", () => {
  it("returns the same array by identity when nothing is pruned", () => {
    const refs: AlwaysOnSkillRef[] = [{ name: "i-have-adhd", source: "user" }];
    expect(pruneAlwaysOnSkillRefs(refs, [skill()])).toBe(refs);
  });

  it("drops refs whose skill no longer exists", () => {
    const refs: AlwaysOnSkillRef[] = [
      { name: "i-have-adhd", source: "user" },
      { name: "gone", source: "codex" },
    ];
    expect(pruneAlwaysOnSkillRefs(refs, [skill()])).toEqual([
      { name: "i-have-adhd", source: "user" },
    ]);
  });
});
