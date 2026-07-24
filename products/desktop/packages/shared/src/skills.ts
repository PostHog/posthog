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
}

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
  meta: { name: string; description: string },
  body: string,
): string {
  const frontmatter = [
    "---",
    `name: ${serializeSkillScalar(meta.name)}`,
    `description: ${serializeSkillScalar(meta.description)}`,
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
