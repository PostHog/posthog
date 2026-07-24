import { xmlToPlainText } from "@posthog/core/message-editor/content";
import type { Task } from "@posthog/shared/domain-types";

export const REGENERATE_INTERVAL = 7;

export function getFallbackTaskTitle(description: string): string {
  const plainText = xmlToPlainText(description).trim();
  return (plainText || "Untitled").slice(0, 255);
}

export function isPlaceholderTaskTitle(
  task: Pick<Task, "title" | "description">,
): boolean {
  if (task.title.trim().length === 0) {
    return true;
  }

  const fallbackTitle = getFallbackTaskTitle(task.description);
  return task.title === fallbackTitle;
}

export function isAutoTitleLocked(task: Task | undefined): boolean {
  if (!task?.title_manually_set) {
    return false;
  }

  return !isPlaceholderTaskTitle(task);
}

export interface TitleGenerationDecision {
  shouldGenerateFromPrompts: boolean;
  shouldGenerateFromTaskDescription: boolean;
}

export function decideTitleGeneration(input: {
  promptCount: number;
  lastGeneratedAtCount: number;
  initialDescriptionHandled: boolean;
  task: Pick<Task, "title" | "description">;
  isTitleLocked?: () => boolean;
  hasSummary?: boolean;
}): TitleGenerationDecision {
  const {
    promptCount,
    lastGeneratedAtCount,
    initialDescriptionHandled,
    task,
    isTitleLocked,
    hasSummary = false,
  } = input;

  // A first fire on an already-long conversation whose title the user renamed
  // and whose summary is already stored would produce nothing usable. Organic
  // triggers (first prompt, every REGENERATE_INTERVAL prompts) still run while
  // renamed so the summary stays current.
  const skipStaleFire =
    promptCount > 1 &&
    lastGeneratedAtCount === 0 &&
    !initialDescriptionHandled &&
    hasSummary &&
    (isTitleLocked?.() ?? false);

  const shouldGenerateFromPrompts =
    !skipStaleFire &&
    ((promptCount === 1 &&
      lastGeneratedAtCount === 0 &&
      !initialDescriptionHandled) ||
      (promptCount > 1 &&
        promptCount - lastGeneratedAtCount >= REGENERATE_INTERVAL));

  const shouldGenerateFromTaskDescription =
    promptCount === 0 &&
    !initialDescriptionHandled &&
    task.description.trim().length > 0 &&
    isPlaceholderTaskTitle(task);

  return { shouldGenerateFromPrompts, shouldGenerateFromTaskDescription };
}

// Prompt-window fires past the first prompt describe the recent conversation,
// not the task, so the title must stay pinned to the original prompt context.
// Later fires may only fill in a title that is still the raw-description
// placeholder (e.g. an earlier generation failed); the summary always
// refreshes regardless.
export function canApplyTitleFromPrompts(
  promptCount: number,
  task: Pick<Task, "title" | "description">,
): boolean {
  return promptCount <= 1 || isPlaceholderTaskTitle(task);
}

export function selectPromptsForTitle(
  prompts: string[],
  promptCount: number,
): string[] {
  const promptsForTitle =
    promptCount === 1 ? prompts : prompts.slice(-REGENERATE_INTERVAL);
  return promptsForTitle;
}

export function formatPromptsForTitleInput(prompts: string[]): string {
  return prompts.map((p, i) => `${i + 1}. ${p}`).join("\n");
}
