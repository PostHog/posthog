import { parseSkillTemplateId } from "../skills/skillTemplateIds";
import type { TaskAutomation } from "../types";

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
