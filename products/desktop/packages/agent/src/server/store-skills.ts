import {
  mkdir,
  readdir,
  readFile,
  rm,
  stat,
  writeFile,
} from "node:fs/promises";
import { homedir } from "node:os";
import { isAbsolute, join, relative } from "node:path";
import { unzipSync } from "fflate";

/**
 * How many skills-store skills a sandbox asks for. The harness lists every
 * discovered skill's name and description in the system prompt on every turn,
 * so the cost of a larger bundle is prompt context, not payload size.
 */
export const STORE_SKILLS_BUNDLE_LIMIT = 20;

/**
 * The store stamps every stub's frontmatter with `metadata.source`. Only a
 * SKILL.md whose frontmatter carries it is treated as disposable: matching the
 * text anywhere in the file would let a real skill that mentions the store be
 * deleted on the next install.
 */
const STORE_SKILL_MARKER_RE =
  /^\s+source:\s*['"]?posthog-skills-store['"]?\s*$/m;
const FRONTMATTER_RE = /^---[^\n]*\n([\s\S]*?)\n---/;

const SKILL_NAME_PATTERN = /^[a-z0-9][a-z0-9-]{0,63}$/;

export interface StoreSkillsInstallResult {
  /** Skill names written to at least one skill root. */
  installed: string[];
  /** Skill names left alone because a non-store skill of that name is already on disk. */
  collisions: string[];
  /** Stubs from an earlier install that are not in this bundle, removed from at least one root. */
  removed: string[];
  /** Archive entries dropped for an unsafe name or path. */
  rejected: number;
  /** Filesystem failures, one per root and skill, so one broken root does not hide the rest. */
  errors: StoreSkillsInstallError[];
}

export interface StoreSkillsInstallError {
  root: string;
  skillName: string | null;
  message: string;
}

export interface StoreSkillRootsOptions {
  home?: string;
  /** Where Claude Code keeps user state; `CLAUDE_CONFIG_DIR` moves it off `~/.claude`. */
  claudeConfigDir?: string;
}

export function getStoreSkillRoots(
  options: StoreSkillRootsOptions = {},
): string[] {
  const home = options.home ?? homedir();
  // `||`, not `??`: the Claude adapter treats an empty CLAUDE_CONFIG_DIR as unset, and so must this.
  const claudeConfigDir =
    options.claudeConfigDir ??
    (process.env.CLAUDE_CONFIG_DIR || join(home, ".claude"));
  return [join(claudeConfigDir, "skills"), join(home, ".agents", "skills")];
}

/**
 * Unpack a skills-store bundle (`<skill-name>/SKILL.md` per skill) into each
 * skill root, and remove any stub from an earlier install that the bundle no
 * longer contains, so a skill the user lost is not advertised on the next
 * session. A directory that already holds a skill not written by the store is
 * never replaced: the sandbox image ships bundled PostHog skills into the same
 * roots, and a stub must not shadow a real skill of the same name.
 *
 * Each root is handled on its own: a read-only or missing root is reported in
 * `errors` and the other roots still get their stubs.
 */
export async function installStoreSkillsArchive(
  archive: Uint8Array,
  skillRoots: string[],
): Promise<StoreSkillsInstallResult> {
  const { skills, rejected } = groupArchiveBySkill(archive);
  const written = new Set<string>();
  const collided = new Set<string>();
  const removed = new Set<string>();
  const errors: StoreSkillsInstallError[] = [];

  for (const root of skillRoots) {
    for (const [skillName, files] of skills) {
      try {
        const skillDir = join(root, skillName);
        if (!(await isReplaceable(skillDir))) {
          collided.add(skillName);
          continue;
        }
        await rm(skillDir, { recursive: true, force: true });
        for (const [relPath, content] of files) {
          const destination = join(skillDir, relPath);
          await mkdir(join(destination, ".."), { recursive: true });
          await writeFile(destination, Buffer.from(content));
        }
        written.add(skillName);
      } catch (error) {
        errors.push({ root, skillName, message: errorMessage(error) });
      }
    }
    try {
      for (const name of await pruneStaleStubs(root, skills)) {
        removed.add(name);
      }
    } catch (error) {
      errors.push({ root, skillName: null, message: errorMessage(error) });
    }
  }

  return {
    installed: [...skills.keys()].filter((name) => written.has(name)),
    collisions: [...skills.keys()].filter((name) => collided.has(name)),
    removed: [...removed].sort(),
    rejected,
    errors,
  };
}

/**
 * Remove every stub the store wrote earlier. Used when the bundle is empty or
 * the feature is off for this user, so stale discovery does not outlive access.
 */
export async function removeStoreSkillStubs(
  skillRoots: string[],
): Promise<Pick<StoreSkillsInstallResult, "removed" | "errors">> {
  const removed = new Set<string>();
  const errors: StoreSkillsInstallError[] = [];
  for (const root of skillRoots) {
    try {
      for (const name of await pruneStaleStubs(root, new Map())) {
        removed.add(name);
      }
    } catch (error) {
      errors.push({ root, skillName: null, message: errorMessage(error) });
    }
  }
  return { removed: [...removed].sort(), errors };
}

/** Names of the store stubs on disk across the roots, for a session that keeps the previous install. */
export async function listStoreSkillStubs(
  skillRoots: string[],
): Promise<string[]> {
  const names = new Set<string>();
  for (const root of skillRoots) {
    try {
      for (const name of await listStoreStubs(root)) {
        names.add(name);
      }
    } catch {
      // A root that cannot be read has no stubs to report.
    }
  }
  return [...names].sort();
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

/** Delete store stubs under `root` that are not in `keep`; return their names. */
async function pruneStaleStubs(
  root: string,
  keep: ReadonlyMap<string, unknown>,
): Promise<string[]> {
  const removed: string[] = [];
  for (const name of await listStoreStubs(root)) {
    if (keep.has(name)) {
      continue;
    }
    await rm(join(root, name), { recursive: true, force: true });
    removed.push(name);
  }
  return removed;
}

/** Names of the directories under `root` whose SKILL.md carries the store marker. */
async function listStoreStubs(root: string): Promise<string[]> {
  const entries = await readdir(root, { withFileTypes: true }).catch(
    (error: NodeJS.ErrnoException) => {
      if (error.code === "ENOENT") {
        return [];
      }
      throw error;
    },
  );
  const names: string[] = [];
  for (const entry of entries) {
    if (entry.isDirectory() && (await isStoreStub(join(root, entry.name)))) {
      names.push(entry.name);
    }
  }
  return names;
}

/**
 * True when nothing is there, or when what is there is a stub the store wrote
 * earlier. A directory with no SKILL.md is somebody else's and is kept.
 */
async function isReplaceable(skillDir: string): Promise<boolean> {
  const present = await stat(skillDir).then(
    () => true,
    (error: NodeJS.ErrnoException) => error.code !== "ENOENT",
  );
  return !present || (await isStoreStub(skillDir));
}

async function isStoreStub(skillDir: string): Promise<boolean> {
  const existing = await readSkillMd(skillDir);
  return existing !== null && hasStoreMarker(existing);
}

/** The SKILL.md text, null when the directory has none, "" when it cannot be read. */
function readSkillMd(skillDir: string): Promise<string | null> {
  return readFile(join(skillDir, "SKILL.md"), "utf-8").catch(
    (error: NodeJS.ErrnoException) => (error.code === "ENOENT" ? null : ""),
  );
}

function hasStoreMarker(skillMd: string): boolean {
  const frontmatter = FRONTMATTER_RE.exec(skillMd)?.[1];
  return frontmatter !== undefined && STORE_SKILL_MARKER_RE.test(frontmatter);
}

function errorMessage(error: unknown): string {
  return error instanceof Error ? error.message : String(error);
}
