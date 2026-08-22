/**
 * Skills that reduce what a run costs, ranked.
 *
 * Two rules hold this list together. Everything here installs and uninstalls
 * in one click: a project that cannot do that does not belong on the list, so
 * there is no half-listed entry with instructions instead of a button. And a
 * measurement is only shown with whose measurement it is, never the project's
 * own figure where an independent trial failed to reproduce it.
 *
 * Deliberately absent: JetBrains/benjamin-plus-skill. Its ruleset measured
 * 17.9% lower cost, but it has no SKILL.md — it works by injecting itself at
 * session start — so the installer cannot fetch it, and its authors measured
 * the same text delivered as a skill folder at -0.5%, not significant.
 */

export interface LeanSkill {
  /** Stable id for the checked record, independent of the repo layout. */
  id: string;
  name: string;
  /** GitHub `owner/repo` the installer fetches. */
  source: string;
  /** Directory inside that repo holding SKILL.md, for the installer. */
  skillId: string;
  /** One line, for the row. */
  summary: string;
  /** How it works, for the detail dialog. */
  mechanism: string;
  /** A measured result, always attributed. Absent when nothing was measured. */
  evidence?: string;
  evidenceSource?: string;
  evidenceUrl?: string;
  /** Where the effect does not apply, so nobody expects it everywhere. */
  caveat?: string;
  license: string;
}

export const LEAN_SKILLS: readonly LeanSkill[] = [
  {
    id: "ponytail",
    name: "Ponytail",
    source: "DietrichGebert/ponytail",
    skillId: "ponytail",
    summary:
      "Pushes the agent toward the simplest solution, so it writes less code.",
    mechanism:
      "A standing ruleset with a seven-rung ladder: does the thing need to exist, does the standard library already do it, does the platform, one line before fifty. It changes what the agent builds, not only how it writes.",
    evidence: "80 paired tasks: about 10% lower cost, no quality difference.",
    evidenceSource: "JetBrains",
    evidenceUrl:
      "https://blog.jetbrains.com/ai/2026/07/ponytail-skill-claude-tested/",
    caveat:
      "Concentrated on larger builds and near zero on small ones. The project's own claim of roughly 20% cheaper did not reproduce.",
    license: "MIT",
  },
  {
    id: "context-budget",
    name: "Context budget",
    source: "affaan-m/ecc",
    skillId: "context-budget",
    summary:
      "Audits what is eating your context and says what to drop or load later.",
    mechanism:
      "Inventories your agents, skills, rules and MCP servers, estimates what each costs per turn, and sorts them into keep, load on demand, and remove.",
    caveat:
      "A diagnostic, not a saving. It claims no figure, and acting on what it finds is what changes anything.",
    license: "MIT",
  },
  {
    id: "caveman",
    name: "Caveman",
    source: "juliusbrussee/caveman",
    skillId: "caveman",
    summary: "Strips filler from the agent's prose, leaving code untouched.",
    mechanism:
      "Drops articles, pleasantries and narration from written output. Code blocks and error strings are preserved verbatim.",
    evidence: "82 paired tasks: output tokens down 8.5%, cost near 10%.",
    evidenceSource: "JetBrains",
    evidenceUrl:
      "https://blog.jetbrains.com/ai/2026/07/speak-to-ai-agents-like-cavemen-tosave-tokens/",
    caveat:
      "Its own frontmatter claims 65%, which that trial contradicts: on coding work the stream is mostly code and tool calls, which it does not touch.",
    // The repository is MIT with several runtime directories carved out under
    // BSL-1.1. Only the MIT-covered skills directory is fetched.
    license: "MIT (skills directory)",
  },
];

/** The project's page, for reading more than the dialog carries. */
export function leanSkillRepoUrl(skill: LeanSkill): string {
  return `https://github.com/${skill.source}`;
}

export function leanSkillById(skillId: string): LeanSkill | null {
  return LEAN_SKILLS.find((skill) => skill.skillId === skillId) ?? null;
}
