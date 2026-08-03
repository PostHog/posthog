import type { SkillInfo, SkillSource } from "@posthog/shared";

// Always-on skills are persisted as {name, source} refs, never paths: every
// task creation re-resolves them against the live skill list, so a skill that
// moved or was reinstalled keeps working and a deleted one drops out silently.
// Repo-source skills are excluded — always-on is a machine-global setting and
// must behave identically for repo and repo-less tasks.
export type AlwaysOnSkillSource = Exclude<SkillSource, "repo">;

export interface AlwaysOnSkillRef {
  name: string;
  source: AlwaysOnSkillSource;
}

export interface ResolvedAlwaysOnSkill {
  name: string;
  source: AlwaysOnSkillSource;
  path: string;
  description: string;
  skillMdBytes: number;
  /** SKILL.md body (frontmatter stripped); read for local runs only. */
  body?: string;
}

export function isAlwaysOnSkillSource(
  source: string | undefined,
): source is AlwaysOnSkillSource {
  return (
    source === "user" ||
    source === "marketplace" ||
    source === "codex" ||
    source === "bundled"
  );
}

function refKey(ref: AlwaysOnSkillRef): string {
  return `${ref.source}:${ref.name}`;
}

function refMatchesSkill(
  ref: AlwaysOnSkillRef,
  skill: Pick<SkillInfo, "name" | "source">,
): boolean {
  return ref.name === skill.name && ref.source === skill.source;
}

export function isAlwaysOnSkill(
  refs: AlwaysOnSkillRef[],
  skill: Pick<SkillInfo, "name" | "source">,
): boolean {
  return refs.some((ref) => refMatchesSkill(ref, skill));
}

export function toggleAlwaysOnSkillRef(
  refs: AlwaysOnSkillRef[],
  skill: Pick<SkillInfo, "name" | "source">,
  enabled: boolean,
): AlwaysOnSkillRef[] {
  if (!isAlwaysOnSkillSource(skill.source)) return refs;
  const without = refs.filter((ref) => !refMatchesSkill(ref, skill));
  return enabled
    ? [...without, { name: skill.name, source: skill.source }]
    : without;
}

/** Drops persisted entries that are malformed or reference a non-toggleable source. */
export function sanitizeAlwaysOnSkillRefs(value: unknown): AlwaysOnSkillRef[] {
  if (!Array.isArray(value)) return [];
  const seen = new Set<string>();
  const refs: AlwaysOnSkillRef[] = [];
  for (const entry of value) {
    const candidate = entry as { name?: unknown; source?: unknown } | null;
    const name = candidate?.name;
    const source = candidate?.source;
    if (typeof name !== "string" || name.length === 0) continue;
    if (typeof source !== "string" || !isAlwaysOnSkillSource(source)) continue;
    const ref: AlwaysOnSkillRef = { name, source };
    if (seen.has(refKey(ref))) continue;
    seen.add(refKey(ref));
    refs.push(ref);
  }
  return refs;
}

export function resolveAlwaysOnSkills(
  refs: AlwaysOnSkillRef[],
  liveSkills: SkillInfo[],
): ResolvedAlwaysOnSkill[] {
  const seen = new Set<string>();
  const resolved: ResolvedAlwaysOnSkill[] = [];
  for (const ref of refs) {
    if (seen.has(refKey(ref))) continue;
    seen.add(refKey(ref));
    const skill = liveSkills.find((candidate) =>
      refMatchesSkill(ref, candidate),
    );
    if (!skill) continue;
    resolved.push({
      name: skill.name,
      source: ref.source,
      path: skill.path,
      description: skill.description,
      skillMdBytes: skill.skillMdBytes,
    });
  }
  return resolved;
}

/** Returns the same array when nothing was pruned, so callers can compare by identity. */
export function pruneAlwaysOnSkillRefs(
  refs: AlwaysOnSkillRef[],
  liveSkills: SkillInfo[],
): AlwaysOnSkillRef[] {
  const pruned = refs.filter((ref) =>
    liveSkills.some((skill) => refMatchesSkill(ref, skill)),
  );
  return pruned.length === refs.length ? refs : pruned;
}
