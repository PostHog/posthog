import { describe, expect, it } from "vitest";
import {
  buildSkillInstructions,
  isTrustedSkillDependency,
  parseSkillContext,
} from "./loopSkill";

describe("buildSkillInstructions", () => {
  it.each([
    { context: "", expected: "/deploy-checks" },
    { context: "   ", expected: "/deploy-checks" },
    {
      context: "Focus on the checkout flow.",
      expected: "/deploy-checks\n\nFocus on the checkout flow.",
    },
  ])("context $context → $expected", ({ context, expected }) => {
    expect(buildSkillInstructions("deploy-checks", context)).toBe(expected);
  });
});

describe("isTrustedSkillDependency", () => {
  const repoPrimary = {
    source: "repo" as const,
    path: "/work/app/.claude/skills/deploy-checks",
  };

  it.each([
    {
      name: "user dependency of a repo skill is rejected",
      // A repository's SKILL.md controls dependency names; trusting user skills
      // here would let it exfiltrate the user's private machine-level skills.
      dep: { source: "user" as const, path: "/home/me/.claude/skills/helper" },
      primary: repoPrimary,
      expected: false,
    },
    {
      name: "user dependency of a user skill is trusted",
      dep: { source: "user" as const, path: "/home/me/.claude/skills/helper" },
      primary: {
        source: "user" as const,
        path: "/home/me/.claude/skills/deploy-checks",
      },
      expected: true,
    },
    {
      name: "sibling from the same repo skills dir is trusted",
      dep: { source: "repo" as const, path: "/work/app/.claude/skills/helper" },
      primary: repoPrimary,
      expected: true,
    },
    {
      name: "same-source skill from another repo is rejected",
      dep: {
        source: "repo" as const,
        path: "/work/other-repo/.claude/skills/helper",
      },
      primary: repoPrimary,
      expected: false,
    },
    {
      name: "cross-source non-user match is rejected",
      dep: {
        source: "marketplace" as const,
        path: "/plugins/x/skills/helper",
      },
      primary: repoPrimary,
      expected: false,
    },
    {
      name: "windows-style sibling paths are compared by directory",
      dep: {
        source: "repo" as const,
        path: "C:\\app\\.claude\\skills\\helper",
      },
      primary: {
        source: "repo" as const,
        path: "C:\\app\\.claude\\skills\\deploy-checks",
      },
      expected: true,
    },
  ])("$name", ({ dep, primary, expected }) => {
    expect(isTrustedSkillDependency(dep, primary)).toBe(expected);
  });
});

describe("parseSkillContext", () => {
  it.each([
    { name: "bare invocation", instructions: "/deploy-checks", expected: "" },
    {
      name: "invocation with context",
      instructions: "/deploy-checks\n\nFocus on churn.",
      expected: "Focus on churn.",
    },
    {
      name: "invocation with single-newline context",
      instructions: "/deploy-checks\nFocus on churn.",
      expected: "Focus on churn.",
    },
    {
      name: "drifted instructions are returned whole",
      instructions: "Do the deploy checks manually.",
      expected: "Do the deploy checks manually.",
    },
    {
      name: "prefix-only slash word is not treated as the invocation",
      instructions: "/deploy-checks-extra\n\nMore.",
      expected: "/deploy-checks-extra\n\nMore.",
    },
  ])("$name", ({ instructions, expected }) => {
    expect(parseSkillContext(instructions, "deploy-checks")).toBe(expected);
  });
});
