/**
 * Skills that reduce what a run costs, ranked.
 *
 * Everything here installs and uninstalls in one click, so there is no
 * half-listed entry carrying instructions instead of a button. A measurement
 * is only shown with whose measurement it is, never the project's own figure
 * where an independent trial failed to reproduce it. What each one does is
 * described from its own SKILL.md, so the description is the skill's behavior
 * rather than a paraphrase of its pitch.
 *
 * Deliberately absent: JetBrains/benjamin-plus-skill. Its ruleset measured
 * -17.9% cost, the best of any of these, but it only works injected into the
 * system prompt — its authors measured the same text as a skill folder at
 * -0.5% — so no one-click install can deliver it. Adopting it means shipping
 * the rules in the prompt every harness appends, which is its own change.
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
  /** How it goes about it, taken from its own instructions. */
  approach: string;
  /** The project's own illustration of the difference it makes. */
  example?: { ask: string; without: string; with: string };
  /**
   * An independent trial's finding, always in the trial's name. A skill
   * nobody measured carries none, and the dialog then shows none rather than
   * a line of ours saying it is unmeasured.
   */
  trial?: {
    source: string;
    /** The figure worth scanning for, e.g. "10%". */
    headline: string;
    /** What that figure is, e.g. "lower cost". */
    headlineLabel: string;
    /** How much work it was measured over, e.g. "80 paired tasks". */
    sample: string;
    /** The rest of the finding, in the trial's terms. */
    finding: string;
    url: string;
  };
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
    approach:
      "A ladder it climbs on every coding task, stopping at the first rung that works: does this need to exist, is it already in the codebase, does the standard library or the platform cover it, is a dependency already installed, can it be one line. Only then does it write the minimum, and it leaves a comment naming each simplification it chose.",
    example: {
      ask: "Asked for a date picker",
      without: "installs a picker library and wraps it in a component",
      with: '<input type="date">',
    },
    trial: {
      source: "JetBrains",
      headline: "10%",
      headlineLabel: "lower cost",
      sample: "80 paired tasks",
      finding:
        "No quality difference. Concentrated on larger builds, near zero on small ones.",
      url: "https://blog.jetbrains.com/ai/2026/07/ponytail-skill-claude-tested/",
    },
    license: "MIT",
  },
  {
    id: "context-budget",
    name: "Context budget",
    source: "affaan-m/ecc",
    skillId: "context-budget",
    summary:
      "Audits what is eating your context and says what to drop or load later.",
    approach:
      "Inventories your agents, skills, rules and MCP servers, estimates what each one costs from its word count, then sorts them into always, sometimes and rarely needed. It ends on the three changes with the largest projected saving, leaving the cutting to you.",
    license: "MIT",
  },
  {
    id: "caveman",
    name: "Caveman",
    source: "juliusbrussee/caveman",
    skillId: "caveman",
    summary: "Strips filler from the agent's prose, leaving code untouched.",
    approach:
      "An output mode that holds for the session: articles, hedges, pleasantries, tables and tool-call narration go, and what is left is written in fragments. Code blocks, API names, commands and error strings stay verbatim, and it refuses invented abbreviations, which cost tokens rather than save them.",
    trial: {
      source: "JetBrains",
      headline: "8.5%",
      headlineLabel: "fewer output tokens",
      sample: "82 paired tasks",
      finding: "Cost down near 10%.",
      url: "https://blog.jetbrains.com/ai/2026/07/speak-to-ai-agents-like-cavemen-tosave-tokens/",
    },
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
