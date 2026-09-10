import {
  contentToPlainText,
  contentToXml,
  type EditorContent,
  textToContent,
  xmlToContent,
} from "@posthog/core/message-editor/content";

const MAX_RECOVERABLE_PROMPTS = 20;

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

/**
 * Capture the durable record fields for a submit, from the composer content
 * the person typed. Wrappers that transform the content for the task request
 * (the autoresearch kickoff prepends a protocol preamble) must derive the
 * record from the original content: recovery restores what the person typed,
 * and a preamble that survives into the composer gets prepended a second time
 * on resubmit.
 */
export function pendingPromptRecordFromContent(content: EditorContent): {
  promptText: string;
  contentXml: string;
  attachments: { id: string; label: string }[];
} {
  return {
    promptText: contentToPlainText(content).trim(),
    contentXml: contentToXml(content).trim(),
    attachments: (content.attachments ?? []).map((attachment) => ({
      id: attachment.id,
      label: attachment.label,
    })),
  };
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
