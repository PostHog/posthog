const SCOUT_SKILL_PREFIX = "signals-scout-";

/** Route param form: "signals-scout-error-tracking" → "error-tracking" */
export function scoutSkillSlug(skillName: string): string {
  return skillName.startsWith(SCOUT_SKILL_PREFIX)
    ? skillName.slice(SCOUT_SKILL_PREFIX.length)
    : skillName;
}

/** Inverse of `scoutSkillSlug`: "error-tracking" → "signals-scout-error-tracking" */
export function scoutSkillNameFromSlug(slug: string): string {
  return slug.startsWith(SCOUT_SKILL_PREFIX)
    ? slug
    : `${SCOUT_SKILL_PREFIX}${slug}`;
}
