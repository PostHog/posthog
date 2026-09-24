import type { DecisionQuestion } from "@posthog/api-client/posthog-client";
import {
  isTaskCategory,
  type TaskCategory,
} from "@posthog/shared/domain-types";
import { xmlToPlainText } from "../message-editor/content";
import type { TaskCreationApiClient } from "./taskCreationApiClient";

const CATEGORY_QUESTION_ID = "category";

// The first prompt decides the category. A long paste adds cost, not signal.
const MAX_PROMPT_CHARS = 8_000;

// A fast decision model answers in well under a second. Past this, give up so a
// stuck request cannot hold the promise open for the life of the session.
export const CATEGORY_TIMEOUT_MS = 5_000;

const CATEGORY_MEANINGS: Record<TaskCategory, string> = {
  feat: "Adds new functionality, a new feature, or a new capability",
  fix: "Fixes a bug, an error, a crash, or other incorrect behavior",
  perf: "Makes something faster or use less memory, CPU, or network",
  refactor: "Restructures or cleans up code without changing its behavior",
  docs: "Changes only documentation, READMEs, or code comments",
  test: "Adds or changes only tests",
  chore:
    "Maintenance with no product change: dependencies, config, tooling, or a question or investigation",
  ci: "Changes CI pipelines, workflows, or automation",
  build: "Changes the build system, bundling, or packaging",
  style: "Changes only formatting, whitespace, or lint issues",
  revert: "Reverts an earlier change",
};

export const TASK_CATEGORY_QUESTION: DecisionQuestion = {
  type: "choice",
  instructions:
    "This is the first message a developer sent to a coding agent. Which conventional commit type best describes the change they are asking for?",
  criteria: CATEGORY_MEANINGS,
};

export function categoryPromptText(prompt: string): string {
  return xmlToPlainText(prompt).trim().slice(0, MAX_PROMPT_CHARS);
}

/**
 * Ask the decision model which conventional commit type the prompt describes.
 * Resolves null when the prompt is empty, the model is unavailable, or the
 * answer is not a known category. Never rejects.
 */
export async function classifyTaskCategory(
  client: Pick<TaskCreationApiClient, "decide">,
  prompt: string,
  timeoutMs: number = CATEGORY_TIMEOUT_MS,
): Promise<TaskCategory | null> {
  const state = categoryPromptText(prompt);
  if (!state) return null;

  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeoutMs);
  try {
    const response = await client.decide({
      state,
      questions: { [CATEGORY_QUESTION_ID]: TASK_CATEGORY_QUESTION },
      signal: controller.signal,
    });
    const choice = response.answers[CATEGORY_QUESTION_ID]?.choice;
    return isTaskCategory(choice) ? choice : null;
  } catch {
    return null;
  } finally {
    clearTimeout(timer);
  }
}
