import { describe, expect, it } from "vitest";
import { isIgnoredSkillEntry, isIgnoredSkillPath } from "./skills";

describe("isIgnoredSkillEntry", () => {
  it.each([
    [".venv", "directory", true],
    [".worktrees", "directory", true],
    [".git", "directory", true],
    [".git", "file", true],
    [".DS_Store", "file", true],
    ["node_modules", "directory", true],
    ["__pycache__", "directory", true],
    [".gitignore", "file", false],
    [".env.example", "file", false],
    ["references", "directory", false],
    ["SKILL.md", "file", false],
  ] as const)("isIgnoredSkillEntry(%j, %j) === %s", (name, kind, expected) => {
    expect(isIgnoredSkillEntry(name, kind)).toBe(expected);
  });
});

describe("isIgnoredSkillPath", () => {
  it.each([
    ["foo/.venv/x.py", true],
    [".worktrees/a/b", true],
    ["node_modules/pkg/index.js", true],
    ["a/.DS_Store", true],
    [".gitignore", false],
    ["docs/.hidden.md", false],
    ["docs/guide.md", false],
    ["foo/", true],
    ["", true],
    ["../escape.md", true],
    ["foo/..", true],
    ["a//b.md", true],
    ["/etc/evil.md", true],
    // A backslash is an ordinary character here, not a separator: this is
    // one literal filename with no "/" in it, so it is kept.
    [".venv\\lib\\mod.py", false],
  ] as const)("isIgnoredSkillPath(%j) === %s", (relativePath, expected) => {
    expect(isIgnoredSkillPath(relativePath)).toBe(expected);
  });
});
