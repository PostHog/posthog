export const SKILL_TEMPLATE_ID_PREFIX = "llm-skill:";

export function formatSkillTemplateId(skillName: string): string {
  return `${SKILL_TEMPLATE_ID_PREFIX}${skillName.trim()}`;
}

export function parseSkillTemplateId(
  templateId: string | null | undefined,
): string | null {
  if (!templateId?.startsWith(SKILL_TEMPLATE_ID_PREFIX)) {
    return null;
  }

  const skillName = templateId.slice(SKILL_TEMPLATE_ID_PREFIX.length).trim();
  return skillName || null;
}
