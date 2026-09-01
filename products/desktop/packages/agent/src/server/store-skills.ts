import { mkdir, readFile, rm, writeFile } from "node:fs/promises";
import { isAbsolute, join, relative } from "node:path";
import { unzipSync } from "fflate";

/**
 * How many skills-store skills a sandbox asks for. The harness lists every
 * discovered skill's name and description in the system prompt on every turn,
 * so the cost of a larger bundle is prompt context, not payload size.
 */
export const STORE_SKILLS_BUNDLE_LIMIT = 20;

/** Frontmatter marker the store writes into every stub SKILL.md. */
const STORE_SKILL_MARKER = "source: posthog-skills-store";

const SKILL_NAME_PATTERN = /^[a-z0-9][a-z0-9-]{0,63}$/;

export interface StoreSkillsInstallResult {
  /** Skill names written to at least one skill root. */
  installed: string[];
  /** Skill names left alone because a non-store skill of that name is already on disk. */
  collisions: string[];
  /** Archive entries dropped for an unsafe name or path. */
  rejected: number;
}

export function getStoreSkillRoots(
  home: string = process.env.HOME ?? "/tmp",
): string[] {
  return [join(home, ".claude", "skills"), join(home, ".agents", "skills")];
}

/**
 * Unpack a skills-store bundle (`<skill-name>/SKILL.md` per skill) into each
 * skill root. A directory that already holds a skill not written by the store
 * is never replaced: the sandbox image ships bundled PostHog skills into the
 * same roots, and a stub must not shadow a real skill of the same name.
 */
export async function installStoreSkillsArchive(
  archive: Uint8Array,
  skillRoots: string[],
): Promise<StoreSkillsInstallResult> {
  const { skills, rejected } = groupArchiveBySkill(archive);
  const installed: string[] = [];
  const collisions: string[] = [];

  for (const [skillName, files] of skills) {
    let writtenAnywhere = false;
    let collided = false;
    for (const root of skillRoots) {
      const skillDir = join(root, skillName);
      if (!(await isReplaceable(skillDir))) {
        collided = true;
        continue;
      }
      await rm(skillDir, { recursive: true, force: true });
      for (const [relPath, content] of files) {
        const destination = join(skillDir, relPath);
        await mkdir(join(destination, ".."), { recursive: true });
        await writeFile(destination, Buffer.from(content));
      }
      writtenAnywhere = true;
    }
    if (writtenAnywhere) {
      installed.push(skillName);
    }
    if (collided) {
      collisions.push(skillName);
    }
  }

  return { installed, collisions, rejected };
}

export function buildStoreSkillsInstructions(installedCount: number): string {
  if (installedCount === 0) {
    return "";
  }
  return `
## Skills from the PostHog skills store
${installedCount} of the user's skills from the PostHog skills store are installed as local skills. Each one's SKILL.md is a pointer, not the skill: when you invoke one, follow the pointer and fetch the skill body with the PostHog MCP \`skill-get\` tool before you act. Never improvise the skill from the pointer text.`;
}

function groupArchiveBySkill(archive: Uint8Array): {
  skills: Map<string, Map<string, Uint8Array>>;
  rejected: number;
} {
  const skills = new Map<string, Map<string, Uint8Array>>();
  const rejectedSkills = new Set<string>();
  let rejected = 0;

  for (const [entryName, content] of Object.entries(unzipSync(archive))) {
    const normalized = entryName.replaceAll("\\", "/");
    if (!normalized || normalized.endsWith("/")) {
      continue;
    }
    const [skillName, ...rest] = normalized.split("/");
    const relPath = rest.join("/");
    if (
      !skillName ||
      !SKILL_NAME_PATTERN.test(skillName) ||
      !isSafeRelativePath(relPath)
    ) {
      rejected += 1;
      if (skillName) {
        rejectedSkills.add(skillName);
      }
      continue;
    }
    let files = skills.get(skillName);
    if (!files) {
      files = new Map();
      skills.set(skillName, files);
    }
    files.set(relPath, content);
  }

  // A skill with one bad entry is dropped whole rather than installed partially.
  for (const skillName of rejectedSkills) {
    skills.delete(skillName);
  }
  for (const [skillName, files] of skills) {
    if (!files.has("SKILL.md")) {
      skills.delete(skillName);
      rejected += 1;
    }
  }

  return { skills, rejected };
}

function isSafeRelativePath(relPath: string): boolean {
  if (!relPath || isAbsolute(relPath)) {
    return false;
  }
  const segments = relPath.split("/");
  if (segments.some((segment) => !segment || segment === "..")) {
    return false;
  }
  const resolved = relative("/root", join("/root", relPath));
  return !!resolved && !resolved.startsWith("..") && !isAbsolute(resolved);
}

/** True when nothing is there, or when what is there is a stub the store wrote earlier. */
async function isReplaceable(skillDir: string): Promise<boolean> {
  const existing = await readFile(join(skillDir, "SKILL.md"), "utf-8").catch(
    (error: NodeJS.ErrnoException) => (error.code === "ENOENT" ? null : ""),
  );
  return existing === null || existing.includes(STORE_SKILL_MARKER);
}
