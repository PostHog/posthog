import {
  type EditorContent,
  textToContent,
  xmlToContent,
} from "@posthog/core/message-editor/content";

export const MAX_RECOVERABLE_PROMPTS = 20;

/** Why a submitted prompt never reached a running task. */
export type PendingPromptInterruptReason = "offline" | "failed";

/** The fields a recovered prompt restores its composer content from. */
export interface RecoverablePromptContent {
  /** Serialized editor content (chips + attachments), preferred on restore. */
  contentXml?: string;
  /** Plain-text fallback for records written before contentXml existed. */
  promptText: string;
}

/**
 * Reconstruct the editor content to drop back into the composer on recovery.
 * Prefers the serialized content so file chips and attachments survive; falls
 * back to plain text for records written before contentXml was captured.
 */
export function pendingPromptToContent(
  record: RecoverablePromptContent,
): EditorContent {
  const xml = record.contentXml?.trim();
  return xml ? xmlToContent(xml) : textToContent(record.promptText);
}

export interface TimestampedPendingPrompt {
  createdAt: number;
}

export interface RecoverablePendingPrompt<
  TPrompt extends TimestampedPendingPrompt,
> {
  key: string;
  prompt: TPrompt;
}

export function capPendingPrompts<TPrompt extends TimestampedPendingPrompt>(
  byKey: Record<string, TPrompt>,
  limit: number = MAX_RECOVERABLE_PROMPTS,
): Record<string, TPrompt> {
  const keys = Object.keys(byKey);
  if (keys.length <= limit) return byKey;

  const kept = keys
    .sort((left, right) => byKey[right].createdAt - byKey[left].createdAt)
    .slice(0, limit);
  return Object.fromEntries(kept.map((key) => [key, byKey[key]]));
}

export function listPendingPromptsNewestFirst<
  TPrompt extends TimestampedPendingPrompt,
>(byKey: Record<string, TPrompt>): RecoverablePendingPrompt<TPrompt>[] {
  return Object.entries(byKey)
    .map(([key, prompt]) => ({ key, prompt }))
    .sort((left, right) => right.prompt.createdAt - left.prompt.createdAt);
}

export function buildPendingPromptKey(
  randomUuid: string | null,
  timestamp: number,
  entropy: string,
): string {
  return randomUuid ?? `pending-${timestamp}-${entropy}`;
}
