/**
 * Helpers for the one-shot "/btw" side question. Pure functions only —
 * the forked query mechanics live in ClaudeAcpAgent.answerSideQuestion.
 */

export const SIDE_QUESTION_TIMEOUT_MS = 120_000;

/**
 * Wraps the user's question in the constraints the fork must obey: no tools,
 * single one-off response, answer only from what the conversation already
 * contains. Mirrors the prompt shape Claude Code uses for its /btw command.
 */
export function buildSideQuestionPrompt(question: string): string {
  return [
    "<system-reminder>",
    "The user is asking a quick side question. This is a one-off response",
    "outside the main conversation; nothing you say here will be visible in",
    "later turns. You have no tools available: you cannot read files, run",
    "commands, search, or take any action. Answer concisely using only the",
    "knowledge already present in the conversation. Never promise actions",
    '(do not say things like "Let me try..." or offer to investigate);',
    "if you do not know the answer, say so plainly.",
    "</system-reminder>",
    "",
    question,
  ].join("\n");
}
