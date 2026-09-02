import type { LoopSchemas } from "@posthog/api-client/loops";

/**
 * The skill driving a loop's instructions in the form. `attached` is the
 * server-stored snapshot (edit mode, unchanged on save); `local` is a skill
 * picked from this machine, bundled and uploaded on save.
 */
export type LoopSkillDraft =
  | {
      kind: "attached";
      name: string;
      source: LoopSchemas.LoopSkillSourceEnum;
    }
  | {
      kind: "local";
      name: string;
      source: LoopSchemas.LoopSkillSourceEnum;
      path: string;
    };

export function buildSkillInstructions(
  skillName: string,
  context: string,
): string {
  const invocation = `/${skillName}`;
  const trimmed = context.trim();
  return trimmed ? `${invocation}\n\n${trimmed}` : invocation;
}

/**
 * The free-text context of skill-driven instructions: everything after the
 * leading `/skill-name` line. Instructions that drifted from that shape are
 * returned whole so nothing the user wrote is hidden.
 */
export function parseSkillContext(
  instructions: string,
  skillName: string,
): string {
  const invocation = `/${skillName}`;
  const trimmed = instructions.trim();
  if (trimmed === invocation) return "";
  if (trimmed.startsWith(`${invocation}\n`)) {
    return trimmed.slice(invocation.length).trim();
  }
  return trimmed;
}

function parentDir(skillPath: string): string {
  const separatorIndex = Math.max(
    skillPath.lastIndexOf("/"),
    skillPath.lastIndexOf("\\"),
  );
  return separatorIndex > 0 ? skillPath.slice(0, separatorIndex) : skillPath;
}

/**
 * Whether a resolved skill dependency may ride along in a loop's bundle set.
 * Dependency names come from the referencing skill's SKILL.md, which for a repo
 * skill is repository-controlled — so only same-source siblings from the same
 * skills directory are trusted. Anything looser leaks: a cross-directory match
 * lets another repo shadow the dependency, and trusting user skills from a repo
 * primary would let a repository declare likely user-skill names and silently
 * upload the user's private machine-level skills.
 */
export function isTrustedSkillDependency(
  dep: { source: LoopSchemas.LoopSkillSourceEnum; path: string },
  primary: { source: LoopSchemas.LoopSkillSourceEnum; path: string },
): boolean {
  return (
    dep.source === primary.source &&
    parentDir(dep.path) === parentDir(primary.path)
  );
}

/** The loop's attached bundles, tolerating a backend that predates the field. */
export function loopSkillBundles(
  loop: LoopSchemas.Loop,
): LoopSchemas.LoopSkillBundle[] {
  return loop.skill_bundles ?? [];
}

/** The bundle whose skill the loop's instructions invoke; dependency bundles follow it. */
export function primaryLoopSkillBundle(
  loop: LoopSchemas.Loop,
): LoopSchemas.LoopSkillBundle | null {
  return loopSkillBundles(loop)[0] ?? null;
}
