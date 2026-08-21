export const MAX_RECOVERABLE_PROMPTS = 20;

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
