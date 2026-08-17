import type { TaskAutomation } from "@posthog/shared";

export const SKILL_TEMPLATE_ID_PREFIX = "llm-skill:";

export function formatSkillTemplateId(skillName: string): string {
  return `${SKILL_TEMPLATE_ID_PREFIX}${skillName.trim()}`;
}

export function parseSkillTemplateId(
  templateId: string | null | undefined,
): string | null {
  if (!templateId?.startsWith(SKILL_TEMPLATE_ID_PREFIX)) return null;
  const skillName = templateId.slice(SKILL_TEMPLATE_ID_PREFIX.length).trim();
  return skillName || null;
}

export interface AutomationTemplatePresentation {
  templateName: string | null;
  repositoryLabel: string | null;
  contextLabel: string | null;
  secondaryLabel: string;
}

export function getAutomationTemplatePresentation(
  automation: Pick<TaskAutomation, "repository" | "template_id">,
): AutomationTemplatePresentation {
  const repositoryLabel = automation.repository.trim() || null;
  const skillName = parseSkillTemplateId(automation.template_id);
  const contextLabel = skillName ? "Skill store" : null;
  return {
    templateName:
      skillName ?? (automation.template_id ? "Template automation" : null),
    repositoryLabel,
    contextLabel,
    secondaryLabel: repositoryLabel ?? contextLabel ?? "No repository context",
  };
}
