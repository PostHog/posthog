import {
  mkdir,
  readdir,
  readFile,
  rename,
  rm,
  stat,
  writeFile,
} from "node:fs/promises";
import { homedir } from "node:os";
import { join } from "node:path";
import type { StoreSkillStub, TaskRunState } from "@posthog/agent-contracts";

/**
 * The store stamps every stub's frontmatter with `metadata.source`. Only a
 * SKILL.md whose frontmatter carries it, as a key of the top-level `metadata`
 * mapping, is treated as disposable: matching the text anywhere in the file,
 * or anywhere indented, would let a real skill that mentions the store in a
 * block-scalar description be deleted on the next install.
 */
const STORE_SKILL_SOURCE = "posthog-skills-store";
const FRONTMATTER_RE = /^---[^\n]*\n([\s\S]*?)\n---/;
const METADATA_KEY_RE = /^metadata:\s*(#.*)?$/;
const SOURCE_VALUE_RE = new RegExp(
  `^source:\\s*['"]?${STORE_SKILL_SOURCE}['"]?\\s*(#.*)?$`,
);
// The bridge also carries the store marker, so pruning and replacement treat it as a stub.
const BRIDGE_ROLE_VALUE_RE = /^role:\s*['"]?bridge['"]?\s*(#.*)?$/;

export const STORE_BRIDGE_SKILL_NAME = "phs";

// The shape half of the store's skill-name contract (skill_name_is_well_formed
// in products/skills/backend/api/skill_services.py). A name is also a directory
// under the skill roots, so nothing that fails it may reach the filesystem.
const SKILL_NAME_PATTERN = /^[a-z0-9]([a-z0-9-]*[a-z0-9])?$/;
const MAX_SKILL_NAME_LENGTH = 64;

export interface StoreSkillsInstallResult {
  /** Skill names written to at least one skill root. */
  installed: string[];
  /** True when the bridge was written to at least one skill root. */
  bridge: boolean;
  /** Skill names left alone because a non-store skill of that name is already on disk. */
  collisions: string[];
  /** Stubs from an earlier install that are not in this list, removed from at least one root. */
  removed: string[];
  /** Entries dropped for an unsafe name, an empty description, or a malformed version. */
  rejected: number;
  /** Filesystem failures, one per root and skill, so one broken root does not hide the rest. */
  errors: StoreSkillsInstallError[];
}

export interface StoreSkillsInstallError {
  root: string;
  skillName: string | null;
  message: string;
}

export interface StoreSkillsListing {
  /** Stubs for the user's own store skills. The bridge is not one of them. */
  installedCount: number;
  bridge: boolean;
}

export const NO_STORE_SKILLS: StoreSkillsListing = {
  installedCount: 0,
  bridge: false,
};

export interface StoreSkillRootsOptions {
  home?: string;
  /** Where Claude Code keeps user state; `CLAUDE_CONFIG_DIR` moves it off `~/.claude`. */
  claudeConfigDir?: string;
}

/**
 * The user-level skill directories every supported harness lists: Claude Code
 * reads its config dir, and Claude Code, Codex and Pi all read `~/.agents/skills`.
 */
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
 * The pointer SKILL.md for one store skill. Keep it in step with
 * `render_skill_stub_md` in products/skills/backend/marketplace/packaging.py,
 * which renders the same file for the bundle endpoint: the frontmatter marker
 * is what `listStoreSkillStubs` keys on, and the body is the fetch contract.
 * The description is written as a JSON string, which is a valid YAML
 * double-quoted scalar, so quotes and newlines in it cannot break the file.
 */
export function renderStoreSkillStub(stub: StoreSkillStub): string {
  const skillGet = `call skill-get {"skill_name": "${stub.name}"}`;
  const skillFileGet = `call skill-file-get {"skill_name": "${stub.name}", "file_path": "<path>", "version": <version>}`;
  return [
    "---",
    `name: ${stub.name}`,
    `description: ${JSON.stringify(stub.description)}`,
    "metadata:",
    `  version: '${stub.version}'`,
    `  source: ${STORE_SKILL_SOURCE}`,
    "---",
    "",
    "This skill lives in the PostHog skills store. This file is a pointer for discovery, not the skill itself.",
    "",
    "Before you act on it:",
    "",
    `1. Run \`${skillGet}\` with the PostHog MCP \`exec\` tool. Note the \`version\` in the response and pass it to every later call for this skill, so a publish in the meantime cannot mix two versions.`,
    '2. If the response has a non-null `body_next_offset`, call `skill-get` again with `"version"` set to that version and `"body_offset"` set to `body_next_offset`, and append the returned `body`. Repeat until `body_next_offset` is null.',
    "3. Follow the complete `body` as the instructions for this skill.",
    `4. If the body references bundled files, fetch each one with \`${skillFileGet}\` and write it into this directory before you use it.`,
    "",
  ].join("\n");
}

/** Reads and runs skills only, because a `read_only` run cannot write to the store. */
export function renderStoreBridgeSkill(): string {
  const name = STORE_BRIDGE_SKILL_NAME;
  const description =
    "Run any skill from the PostHog skills store by name, including a teammate's skill that is not installed here. " +
    `Use when the user types /${name} <skill-name> [arguments], asks to run a store skill that is not installed, or asks which store skills exist.`;
  return [
    "---",
    `name: ${name}`,
    `description: ${JSON.stringify(description)}`,
    "metadata:",
    `  source: ${STORE_SKILL_SOURCE}`,
    "  role: bridge",
    "---",
    "",
    "This skill runs skills from the PostHog skills store. It only reads and runs them. To create, edit or publish a skill, follow the `skills-store` guidance instead.",
    "",
    `Read the text the user gave after \`${name}\`. The first word selects what to do, and the rest is the arguments. Run every call below with the PostHog MCP \`exec\` tool.`,
    "",
    "## List skills",
    "",
    'When there is no text, or the first word is `list`, run `call skill-list {}`. When a keyword follows `list`, run `call skill-list {"search": "<keyword>"}` instead. Show each skill\'s name and description, then stop.',
    "",
    "## Run a skill",
    "",
    "Otherwise the first word is the name of the skill to run.",
    "",
    '1. Run `call skill-get {"skill_name": "<name>"}`. Note the `version` in the response and pass it to every later call for this skill, so a publish in the meantime cannot mix two versions.',
    '2. If the response has a non-null `body_next_offset`, call `skill-get` again with `"version"` set to that version and `"body_offset"` set to `body_next_offset`, and append the returned `body`. Repeat until `body_next_offset` is null.',
    "3. Follow the complete `body` as the instructions for this task, with the rest of the user's text as its arguments.",
    '4. When the body references a bundled file, fetch it with `call skill-file-get {"skill_name": "<name>", "file_path": "<path>", "version": <version>}` only when you need it.',
    "",
    'If `skill-get` finds no skill with that name, run `call skill-list {"search": "<name>"}` and show the closest matches. Never improvise a skill you could not fetch.',
    "",
  ].join("\n");
}

export interface StoreSkillsLogger {
  info(message: string, data?: unknown): void;
  warn(message: string, data?: unknown): void;
}

export interface StoreSkillsSyncContext {
  taskId: string;
  runId: string;
}

/**
 * Bring the skill roots in line with a run's `store_skills` and
 * `store_skills_bridge`, and return what the harness will list. Shared by
 * every agent server so a runtime cannot drift from the others. Never throws:
 * a run without store skills is the normal case, and a broken root must not
 * stop the session.
 *
 * A null run state says nothing about access, so stubs and the bridge from an
 * earlier session stay and still count: the harness lists them, so the
 * pointer instructions must stay in the prompt too.
 */
export async function syncStoreSkills(
  runState: TaskRunState | null | undefined,
  context: StoreSkillsSyncContext,
  logger: StoreSkillsLogger,
  roots: string[] = getStoreSkillRoots(),
): Promise<StoreSkillsListing> {
  try {
    if (runState === null || runState === undefined) {
      const retained = await readStoreListing(roots);
      if (retained.names.length > 0 || retained.bridge) {
        logger.warn(
          "Run context unavailable, keeping earlier skills store stubs",
          { ...context, retained: retained.names, bridge: retained.bridge },
        );
      }
      return { installedCount: retained.names.length, bridge: retained.bridge };
    }
    const stubs = runState.store_skills ?? [];
    const bridge = runState.store_skills_bridge === true;
    if (stubs.length === 0 && !bridge) {
      const cleanup = await removeStoreSkillStubs(roots);
      if (cleanup.removed.length > 0 || cleanup.errors.length > 0) {
        logger.info("Removed stale skills store stubs", {
          ...context,
          removed: cleanup.removed,
          errors: cleanup.errors,
        });
      }
      return NO_STORE_SKILLS;
    }
    const install = await installStoreSkillStubs(stubs, roots, { bridge });
    logger.info("Installed skills store stubs", {
      ...context,
      listed: stubs.length,
      installed: install.installed,
      bridge: install.bridge,
      collisions: install.collisions,
      removed: install.removed,
      rejected: install.rejected,
      errors: install.errors,
    });
    return {
      installedCount: install.installed.length,
      bridge: install.bridge,
    };
  } catch (error) {
    logger.warn("Skills store install failed", { ...context, error });
    return NO_STORE_SKILLS;
  }
}

export interface InstallStoreSkillStubsOptions {
  bridge?: boolean;
}

/**
 * Write one pointer SKILL.md per stub into each skill root, and remove any
 * stub from an earlier install that the list no longer contains, so a skill
 * the user lost is not advertised on the next session. A directory that
 * already holds a skill not written by the store is never replaced: the
 * sandbox image ships bundled PostHog skills into the same roots, and a stub
 * must not shadow a real skill of the same name.
 *
 * Each root is handled on its own: a read-only or missing root is reported in
 * `errors` and the other roots still get their stubs.
 *
 * The bridge follows the same rules, so it never replaces a non-store skill
 * named `phs`, and a team skill of that name in `stubs` replaces it.
 */
export async function installStoreSkillStubs(
  stubs: readonly StoreSkillStub[],
  skillRoots: string[],
  options: InstallStoreSkillStubsOptions = {},
): Promise<StoreSkillsInstallResult> {
  const { skills, rejected } = selectInstallable(stubs);
  const wantBridge =
    options.bridge === true && !skills.has(STORE_BRIDGE_SKILL_NAME);
  const keep = new Set<string>(skills.keys());
  if (wantBridge) {
    keep.add(STORE_BRIDGE_SKILL_NAME);
  }
  const written = new Set<string>();
  const collided = new Set<string>();
  const removed = new Set<string>();
  const errors: StoreSkillsInstallError[] = [];
  let bridgeWritten = false;

  for (const root of skillRoots) {
    for (const [skillName, stub] of skills) {
      try {
        const skillDir = join(root, skillName);
        if (!(await isReplaceable(skillDir))) {
          collided.add(skillName);
          continue;
        }
        await replaceStub(root, skillName, renderStoreSkillStub(stub));
        written.add(skillName);
      } catch (error) {
        errors.push({ root, skillName, message: errorMessage(error) });
      }
    }
    if (wantBridge) {
      const skillName = STORE_BRIDGE_SKILL_NAME;
      try {
        if (await isReplaceable(join(root, skillName))) {
          await replaceStub(root, skillName, renderStoreBridgeSkill());
          bridgeWritten = true;
        }
      } catch (error) {
        errors.push({ root, skillName, message: errorMessage(error) });
      }
    }
    const pruned = await pruneStaleStubs(root, keep);
    for (const name of pruned.removed) {
      removed.add(name);
    }
    errors.push(...pruned.errors);
  }

  return {
    installed: [...skills.keys()].filter((name) => written.has(name)),
    bridge: bridgeWritten,
    collisions: [...skills.keys()].filter((name) => collided.has(name)),
    removed: [...removed].sort(),
    rejected,
    errors,
  };
}

/**
 * Remove every stub the store wrote earlier, the bridge included. Used when
 * the run lists no store skills, so stale discovery does not outlive access.
 */
export async function removeStoreSkillStubs(
  skillRoots: string[],
): Promise<Pick<StoreSkillsInstallResult, "removed" | "errors">> {
  const removed = new Set<string>();
  const errors: StoreSkillsInstallError[] = [];
  for (const root of skillRoots) {
    const pruned = await pruneStaleStubs(root, new Set());
    for (const name of pruned.removed) {
      removed.add(name);
    }
    errors.push(...pruned.errors);
  }
  return { removed: [...removed].sort(), errors };
}

/** Names of the store stubs on disk across the roots, the bridge excluded, for a session that keeps the previous install. */
export async function listStoreSkillStubs(
  skillRoots: string[],
): Promise<string[]> {
  return (await readStoreListing(skillRoots)).names;
}

async function readStoreListing(
  skillRoots: string[],
): Promise<{ names: string[]; bridge: boolean }> {
  const names = new Set<string>();
  let bridge = false;
  for (const root of skillRoots) {
    try {
      for (const stub of await listStoreStubs(root)) {
        if (stub.bridge) {
          bridge = true;
        } else {
          names.add(stub.name);
        }
      }
    } catch {
      // A root that cannot be read has no stubs to report.
    }
  }
  return { names: [...names].sort(), bridge };
}

export function buildStoreSkillsInstructions(
  listing: StoreSkillsListing,
): string {
  const sections: string[] = [];
  if (listing.installedCount > 0) {
    sections.push(
      `${listing.installedCount} of the user's skills from the PostHog skills store are installed as local skills. Each one's SKILL.md is a pointer, not the skill: when you invoke one, follow the pointer and fetch the skill body with the PostHog MCP \`skill-get\` tool before you act. Never improvise the skill from the pointer text.`,
    );
  }
  if (listing.bridge) {
    sections.push(
      `To run a store skill that is not installed here, such as a teammate's, use the \`${STORE_BRIDGE_SKILL_NAME}\` skill: \`/${STORE_BRIDGE_SKILL_NAME} <skill-name> [arguments]\` runs it, and \`/${STORE_BRIDGE_SKILL_NAME} list [keyword]\` lists the store.`,
    );
  }
  if (sections.length === 0) {
    return "";
  }
  return `
## Skills from the PostHog skills store
${sections.join("\n")}`;
}

function selectInstallable(stubs: readonly StoreSkillStub[]): {
  skills: Map<string, StoreSkillStub>;
  rejected: number;
} {
  const skills = new Map<string, StoreSkillStub>();
  let rejected = 0;
  for (const stub of stubs) {
    if (
      !isWellFormedSkillName(stub.name) ||
      stub.description.trim().length === 0 ||
      !Number.isInteger(stub.version) ||
      stub.version < 0 ||
      skills.has(stub.name)
    ) {
      rejected += 1;
      continue;
    }
    skills.set(stub.name, stub);
  }
  return { skills, rejected };
}

function isWellFormedSkillName(name: string): boolean {
  return (
    name.length <= MAX_SKILL_NAME_LENGTH &&
    SKILL_NAME_PATTERN.test(name) &&
    !name.includes("--")
  );
}

/**
 * Stage the new stub beside its destination and rename it into place, so the
 * skill directory is either the previous stub or the complete new one. A
 * write that stops halfway would otherwise leave a markerless directory that
 * `isReplaceable` keeps as somebody else's skill on every later session.
 */
async function replaceStub(
  root: string,
  skillName: string,
  skillMd: string,
): Promise<void> {
  const skillDir = join(root, skillName);
  // Dot-prefixed, so a harness that scans the root for skills skips it while it is being written.
  const stagingDir = join(root, `.${skillName}.store-stub-${process.pid}`);
  try {
    await rm(stagingDir, { recursive: true, force: true });
    await mkdir(stagingDir, { recursive: true });
    await writeFile(join(stagingDir, "SKILL.md"), skillMd);
    await rm(skillDir, { recursive: true, force: true });
    await rename(stagingDir, skillDir);
  } catch (error) {
    await rm(stagingDir, { recursive: true, force: true }).catch(() => {});
    throw error;
  }
}

/**
 * Delete store stubs under `root` that are not in `keep`. A stub that cannot
 * be removed is reported and the walk goes on, so one busy directory does not
 * leave every later stale stub discoverable.
 */
async function pruneStaleStubs(
  root: string,
  keep: ReadonlySet<string>,
): Promise<Pick<StoreSkillsInstallResult, "removed" | "errors">> {
  const removed: string[] = [];
  const errors: StoreSkillsInstallError[] = [];
  let stale: string[];
  try {
    stale = (await listStoreStubs(root))
      .map((stub) => stub.name)
      .filter((name) => !keep.has(name));
  } catch (error) {
    return {
      removed,
      errors: [{ root, skillName: null, message: errorMessage(error) }],
    };
  }
  for (const name of stale) {
    try {
      await rm(join(root, name), { recursive: true, force: true });
      removed.push(name);
    } catch (error) {
      errors.push({ root, skillName: name, message: errorMessage(error) });
    }
  }
  return { removed, errors };
}

/** The directories under `root` whose SKILL.md carries the store marker. */
async function listStoreStubs(
  root: string,
): Promise<{ name: string; bridge: boolean }[]> {
  const entries = await readdir(root, { withFileTypes: true }).catch(
    (error: NodeJS.ErrnoException) => {
      if (error.code === "ENOENT") {
        return [];
      }
      throw error;
    },
  );
  const stubs: { name: string; bridge: boolean }[] = [];
  for (const entry of entries) {
    if (!entry.isDirectory()) {
      continue;
    }
    const skillMd = await readSkillMd(join(root, entry.name));
    if (skillMd !== null && hasStoreMarker(skillMd)) {
      stubs.push({
        name: entry.name,
        bridge: hasMetadataEntry(skillMd, BRIDGE_ROLE_VALUE_RE),
      });
    }
  }
  return stubs;
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

/**
 * True when the frontmatter's top-level `metadata` mapping has
 * `source: posthog-skills-store` as a direct key. Walks the block by
 * indentation instead of parsing YAML: the two shapes the store writes and a
 * hand-written skill can take are both plain block mappings, and a full parser
 * would be a dependency just for this check.
 */
export function hasStoreMarker(skillMd: string): boolean {
  return hasMetadataEntry(skillMd, SOURCE_VALUE_RE);
}

function hasMetadataEntry(skillMd: string, entryRe: RegExp): boolean {
  const frontmatter = FRONTMATTER_RE.exec(skillMd)?.[1];
  if (frontmatter === undefined) {
    return false;
  }
  const lines = frontmatter.split("\n");
  const metadataIndex = lines.findIndex((line) => METADATA_KEY_RE.test(line));
  if (metadataIndex === -1) {
    return false;
  }
  let blockIndent: number | null = null;
  for (const line of lines.slice(metadataIndex + 1)) {
    if (line.trim().length === 0) {
      continue;
    }
    const indent = line.length - line.trimStart().length;
    if (indent === 0) {
      return false;
    }
    blockIndent ??= indent;
    if (indent === blockIndent && entryRe.test(line.trim())) {
      return true;
    }
  }
  return false;
}

function errorMessage(error: unknown): string {
  return error instanceof Error ? error.message : String(error);
}
