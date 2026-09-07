import type { SkillInfo, SkillSource } from "@posthog/shared";

export type SkillIssueType =
  | "missing-description"
  | "name-mismatch"
  | "oversized-manifest"
  | "shadowed";

export interface SkillIssue {
  type: SkillIssueType;
  message: string;
}

/** Issues keyed by skill path. Paths without issues are absent. */
export type SkillAnalysis = Record<string, SkillIssue[]>;

/** SKILL.md is injected into agent context; warn when it gets expensive. */
export const OVERSIZED_SKILL_MD_BYTES = 32 * 1024;

/**
 * Precedence when two skills share a name: the most specific source wins.
 * Repo skills beat user skills beat marketplace plugins beat bundled ones.
 */
const SOURCE_PRECEDENCE: SkillSource[] = [
  "repo",
  "user",
  "marketplace",
  "bundled",
  "codex",
];

const SOURCE_LABEL: Record<SkillSource, string> = {
  repo: "repository",
  user: "user",
  marketplace: "marketplace",
  bundled: "bundled",
  codex: "Codex",
};

function precedence(source: SkillSource): number {
  const index = SOURCE_PRECEDENCE.indexOf(source);
  return index === -1 ? SOURCE_PRECEDENCE.length : index;
}

function directoryName(skillPath: string): string {
  return skillPath.split(/[/\\]/).filter(Boolean).pop() ?? skillPath;
}

/** Pure health analysis over the discovered skills. No I/O. */
export function analyzeSkills(skills: SkillInfo[]): SkillAnalysis {
  const analysis: SkillAnalysis = {};
  const push = (skill: SkillInfo, issue: SkillIssue) => {
    const issues = analysis[skill.path] ?? [];
    issues.push(issue);
    analysis[skill.path] = issues;
  };

  for (const skill of skills) {
    if (!skill.description.trim()) {
      push(skill, {
        type: "missing-description",
        message:
          "No description — agents rely on it to decide when to use this skill",
      });
    }

    const dirName = directoryName(skill.path);
    if (skill.name !== dirName) {
      push(skill, {
        type: "name-mismatch",
        message: `Frontmatter name "${skill.name}" does not match the directory name "${dirName}"`,
      });
    }

    if (skill.skillMdBytes > OVERSIZED_SKILL_MD_BYTES) {
      push(skill, {
        type: "oversized-manifest",
        message: `SKILL.md is ${Math.round(skill.skillMdBytes / 1024)} kB — large manifests add context cost every time the skill is used`,
      });
    }
  }

  const byName = new Map<string, SkillInfo[]>();
  for (const skill of skills) {
    const group = byName.get(skill.name);
    if (group) group.push(skill);
    else byName.set(skill.name, [skill]);
  }

  for (const [name, group] of byName) {
    if (group.length < 2) continue;
    const sorted = [...group].sort(
      (a, b) => precedence(a.source) - precedence(b.source),
    );
    const winner = sorted[0];
    if (!winner) continue;
    const winnerLabel = winner.repoName
      ? `${SOURCE_LABEL[winner.source]} (${winner.repoName})`
      : SOURCE_LABEL[winner.source];
    for (const shadowed of sorted.slice(1)) {
      push(shadowed, {
        type: "shadowed",
        message: `Shadowed by the ${winnerLabel} skill named "${name}"`,
      });
    }
  }

  return analysis;
}
