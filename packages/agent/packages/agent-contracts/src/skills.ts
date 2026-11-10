export type SkillSource = "bundled" | "user" | "repo" | "marketplace" | "codex";
export type UploadableSkillSource = Exclude<SkillSource, "bundled">;

export interface SkillInfo {
  name: string;
  description: string;
  source: SkillSource;
  path: string;
  repoName?: string;
  /** Whether the skill lives in a directory we own on the user's behalf. */
  editable: boolean;
  /** Size of SKILL.md in bytes (context-cost signal). */
  skillMdBytes: number;
  /** Frontmatter `disable-model-invocation: true`: only an explicit user invocation runs the skill, never the agent on its own. */
  disableModelInvocation?: boolean;
  enabled?: boolean;
}

export interface SkillFileEntry {
  /** Path relative to the skill directory, using "/" separators. */
  path: string;
  size: number;
}

export interface ExportedSkillFile {
  /** Path relative to the skill directory, using "/" separators. */
  path: string;
  content: string;
}

/** A skill serialized for transport: team publish and install. */
export interface ExportedSkill {
  name: string;
  description: string;
  body: string;
  files: ExportedSkillFile[];
  disableModelInvocation?: boolean;
}

export const DISABLE_MODEL_INVOCATION_METADATA_KEY = "disable-model-invocation";

/**
 * Serializes a SKILL.md file from frontmatter metadata plus a markdown body.
 *
 * The output must round-trip through `parseSkillFrontmatter` and also be valid
 * YAML for the agents that consume these files, so scalars fall back from plain
 * → double-quoted → literal block as they get more hostile. Lives here (shared)
 * so both the workspace-server bundler and the web-host bundler produce the
 * exact same SKILL.md — this is a serialization contract consumed by the cloud
 * sandbox, so it must not drift between hosts.
 */
export function serializeSkillMarkdown(
  meta: {
    name: string;
    description: string;
    disableModelInvocation?: boolean;
  },
  body: string,
): string {
  const frontmatter = [
    "---",
    `name: ${serializeSkillScalar(meta.name)}`,
    `description: ${serializeSkillScalar(meta.description)}`,
    ...(meta.disableModelInvocation ? ["disable-model-invocation: true"] : []),
    "---",
  ].join("\n");

  const trimmedBody = body.replace(/^\n+/, "");
  return `${frontmatter}\n\n${trimmedBody.trimEnd()}\n`;
}

const SKILL_PLAIN_SAFE = /^[A-Za-z0-9][A-Za-z0-9 _.,;()/-]*$/;

function serializeSkillScalar(value: string): string {
  if (value === "") return '""';
  if (!value.includes("\n")) {
    if (SKILL_PLAIN_SAFE.test(value) && !value.endsWith(" ")) return value;
    if (!value.includes('"') && !value.includes("\\")) return `"${value}"`;
  }
  // Literal block: survives quotes, backslashes, and newlines.
  const lines = value
    .split("\n")
    .map((line) => (line.trim() ? `  ${line}` : ""));
  return `|-\n${lines.join("\n")}`;
}

/**
 * Server "skill already exists" messages must include this marker verbatim;
 * the UI keys its overwrite-confirmation flow on it.
 */
export const SKILL_EXISTS_MARKER = "already exists";

/**
 * Strips a leading YAML frontmatter block from a SKILL.md document.
 * CRLF-aware so render (UI) and export (workspace-server) agree on the body.
 */
export function stripFrontmatter(content: string): string {
  const match = content.match(/^---[ \t]*\r?\n[\s\S]*?\r?\n---[ \t]*\r?\n?/);
  if (!match) return content;
  return content.slice(match[0].length).replace(/^(?:[ \t]*\r?\n)+/, "");
}

const IGNORED_SKILL_ENTRIES: ReadonlySet<string> = new Set([
  ".DS_Store",
  ".git",
  "node_modules",
  "__pycache__",
]);

/**
 * Whether a skill directory entry is excluded from skill walks. Lives here
 * (shared) so the file tree, team export, and cloud bundlers all agree on a
 * skill's contents. Dot-directories are never skill content: skill-private
 * state like a `.worktrees` or `.venv` would otherwise count toward the
 * bundle file limit and upload with the skill. Dot-files such as `.gitignore`
 * are legitimate assets and stay. The literal set covers junk that is not
 * dot-named, plus `.git` when it is a worktree pointer file.
 */
export function isIgnoredSkillEntry(
  name: string,
  kind: "file" | "directory",
): boolean {
  if (IGNORED_SKILL_ENTRIES.has(name)) return true;
  return kind === "directory" && name.startsWith(".");
}

/**
 * Path form of `isIgnoredSkillEntry` for callers holding "/"-separated
 * relative paths instead of walking a directory (the web bundler's
 * API-supplied file lists, per `ExportedSkillFile`'s "using '/' separators"
 * contract): every non-final segment is a directory and the final segment is
 * the file. A backslash is an ordinary character, never a separator — this
 * function is host-neutral and cannot assume a platform's path semantics, so
 * a caller with a raw OS-native path decides for itself whether a backslash
 * should be normalized or rejected. Empty segments (which cover "", trailing
 * slashes, and absolute or doubled-slash paths) and `.`/`..` segments are
 * rejected too, which hardens against hostile API-supplied paths.
 */
export function isIgnoredSkillPath(relativePath: string): boolean {
  const segments = relativePath.split("/");
  return segments.some((segment, index) => {
    if (!segment || segment === "." || segment === "..") return true;
    return isIgnoredSkillEntry(
      segment,
      index === segments.length - 1 ? "file" : "directory",
    );
  });
}
