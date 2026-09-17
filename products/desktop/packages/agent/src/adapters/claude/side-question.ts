/**
 * Helpers for the one-shot "/btw" side question. Session-independent only —
 * the forked query mechanics live in ClaudeAcpAgent.answerSideQuestion.
 */

import { RequestError } from "@agentclientprotocol/sdk";
import type { SDKMessage } from "@anthropic-ai/claude-agent-sdk";

export const SIDE_QUESTION_TIMEOUT_MS = 120_000;

/**
 * Drains the one-shot fork's message stream and returns the assistant's
 * answer text. Throws when the turn ends in an error result.
 */
export async function collectSideQuestionAnswer(
  messages: AsyncIterable<SDKMessage>,
): Promise<string> {
  const chunks: string[] = [];
  for await (const message of messages) {
    if (message.type === "assistant") {
      for (const block of message.message.content) {
        if (block.type === "text") {
          chunks.push(block.text);
        }
      }
    } else if (message.type === "result") {
      if (message.subtype !== "success") {
        throw new RequestError(
          -32603,
          `Side question failed: ${message.subtype}`,
        );
      }
      break;
    }
  }
  return chunks.join("").trim();
}

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
