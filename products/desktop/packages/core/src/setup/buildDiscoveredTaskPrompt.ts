import type { DiscoveredTask } from "@posthog/core/setup/types";
import { SKILL_BUTTON_CATALOG } from "@posthog/core/skill-buttons/catalog";

function buildExperimentTaskPrompt(task: DiscoveredTask): string {
  const sections: string[] = [
    SKILL_BUTTON_CATALOG["run-experiment"].prompt,
    "",
    "Use the analysis below as the starting point.",
    "",
    `Hypothesis: ${task.title}`,
    "",
    task.description,
  ];

  if (task.impact) {
    sections.push("", "Primary metric:", task.impact);
  }

  if (task.recommendation) {
    sections.push("", "Proposed variants:", task.recommendation);
  }

  if (task.file) {
    const location = task.lineHint
      ? `${task.file}:${task.lineHint}`
      : task.file;
    sections.push("", `Surface: ${location}`);
  }

  return sections.join("\n");
}

export function buildDiscoveredTaskPrompt(task: DiscoveredTask): string {
  if (task.prompt) return task.prompt;
  if (task.category === "experiment") {
    return buildExperimentTaskPrompt(task);
  }

  const sections: string[] = [
    "Investigate this issue and implement the fix. Open a PR if appropriate.",
    "",
    task.title,
    "",
    task.description,
  ];

  if (task.impact) {
    sections.push("", "Why it matters:", task.impact);
  }

  if (task.recommendation) {
    sections.push("", "Suggested approach:", task.recommendation);
  }

  if (task.file) {
    const location = task.lineHint
      ? `${task.file}:${task.lineHint}`
      : task.file;
    sections.push("", `File: ${location}`);
  }

  return sections.join("\n");
}
