export interface InstalledSkillPromptData {
  skillName: string;
  skillDefinition: string;
  skillRoot: string;
}

export interface LocalSkillInvocation {
  skillName: string;
  args?: string;
}

export function parseLocalSkillInvocation(
  textValue: string,
): LocalSkillInvocation | null {
  const trimmed = textValue.trim();
  const match = trimmed.match(/^\/([^\s]+)(?:\s+([\s\S]*))?$/);
  if (!match?.[1]) {
    return null;
  }

  return {
    skillName: match[1],
    ...(match[2]?.trim() ? { args: match[2].trim() } : {}),
  };
}

export function buildInstalledSkillPrompt(
  skill: InstalledSkillPromptData,
  args: string | undefined,
  coInstalledSkills: readonly InstalledSkillPromptData[] = [],
): string {
  return [
    `The user invoked the local skill "/${skill.skillName}". Apply these skill instructions for this turn.`,
    "",
    `--- BEGIN LOCAL SKILL ${skill.skillName} ---`,
    skill.skillDefinition.trim(),
    `--- END LOCAL SKILL ${skill.skillName} ---`,
    "",
    `Installed skill path: ${skill.skillRoot}`,
    ...(coInstalledSkills.length > 0
      ? [
          "",
          "Other local skills installed for this run (when the skill above references one of these, read its SKILL.md from the listed path):",
          ...coInstalledSkills.map(
            (coInstalled) =>
              `- /${coInstalled.skillName}: ${coInstalled.skillRoot}`,
          ),
        ]
      : []),
    "",
    "User request:",
    args?.trim() || `Run /${skill.skillName}.`,
  ].join("\n");
}

export function buildAttachedSkillsPrompt(
  installedSkills: readonly InstalledSkillPromptData[],
  messageText: string,
): string | null {
  if (installedSkills.length === 0) {
    return null;
  }

  const mentioned = installedSkills.filter((skill) => {
    const escaped = skill.skillName.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
    return new RegExp(
      `(^|[\\s(\`"'\\[])/${escaped}(?![A-Za-z0-9_/-])`,
      "m",
    ).test(messageText);
  });
  const unmentioned = installedSkills.filter(
    (skill) => !mentioned.includes(skill),
  );

  const sections: string[] = [
    "The user's message references local skills that are now installed for this run. Apply a skill's instructions when the message calls for it.",
  ];
  for (const skill of mentioned) {
    sections.push(
      "",
      `--- BEGIN LOCAL SKILL ${skill.skillName} ---`,
      skill.skillDefinition.trim(),
      `--- END LOCAL SKILL ${skill.skillName} ---`,
      `Installed skill path: ${skill.skillRoot}`,
    );
  }
  if (unmentioned.length > 0) {
    sections.push(
      "",
      "Other local skills installed for this run (read a skill's SKILL.md from its path when referenced):",
      ...unmentioned.map(
        (skill) => `- /${skill.skillName}: ${skill.skillRoot}`,
      ),
    );
  }
  return sections.join("\n");
}
