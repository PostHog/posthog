// A task's initial prompt may carry the user's always-on skills wrapped in an
// `<always_on_skills> ... </always_on_skills>` element (see
// buildAlwaysOnSkillsCloudText / buildAlwaysOnSkillsBlock in @posthog/core).
// The conversation UI strips the element and shows a compact chip instead of
// rendering skill manifests or bodies inline.
//
// The tag alone is not enough to identify injected metadata: users may include
// the same XML in examples they want displayed verbatim. Match the fixed
// preamble the builders emit so only system-generated blocks are hidden.
const ALWAYS_ON_SKILLS_REGEX =
  /<always_on_skills\b[^>]*>(\r?\nThe user has marked these skills as always-on[\s\S]*?)<\/always_on_skills>/;

const INLINED_SKILL_NAME_REGEX = /^--- BEGIN ALWAYS-ON SKILL (.+) ---$/gm;
const REFERENCED_SKILL_NAME_REGEX = /^- \/([^\s:]+)/gm;

export interface AlwaysOnSkillsMention {
  /** Injected skill names, inlined entries first. Best-effort, for the chip count. */
  names: string[];
  /** The exact text that was sent inside the element. */
  body: string;
}

export function hasAlwaysOnSkills(content: string): boolean {
  return ALWAYS_ON_SKILLS_REGEX.test(content);
}

// Returns the parsed mention plus the message text with the element removed
// (so the user's own prompt renders cleanly), or null when the content has no
// always-on-skills element.
export function extractAlwaysOnSkills(content: string): {
  mention: AlwaysOnSkillsMention;
  stripped: string;
} | null {
  const match = ALWAYS_ON_SKILLS_REGEX.exec(content);
  if (match?.index === undefined) return null;

  const body = match[1].trim();
  const names = [
    ...[...body.matchAll(INLINED_SKILL_NAME_REGEX)].map((m) => m[1]),
    ...[...body.matchAll(REFERENCED_SKILL_NAME_REGEX)].map((m) => m[1]),
  ];
  const stripped = (
    content.slice(0, match.index) + content.slice(match.index + match[0].length)
  ).trim();

  return { mention: { names, body }, stripped };
}
