import type { ReactNode } from "react";

export interface FeedQuerySuggestion {
  insert: string;
  label: string;
  hint?: string;
  icon?: ReactNode;
}

export interface FeedQueryEditContext {
  chunk: { start: number; end: number; text: string };
  activeKey: string | null;
  typed: string;
  // Completion matches without `not:`, so replacements restore it to avoid inverting the filter.
  valueNegated: boolean;
}

export const FEED_QUERY_KEY_LABELS = [
  "created-by:",
  "commented-by:",
  "mentions:",
  "involves:",
  "space:",
  "repo:",
  "status:",
  "is:",
  "origin:",
  "pr:",
  "ci:",
  "type:",
  "saved:",
] as const;

export function unfinishedFilterKeys(
  text: string,
): { word: string; keys: string[] }[] {
  const candidates: { word: string; keys: string[] }[] = [];

  for (const word of text.split(/\s+/)) {
    if (word === "") continue;

    const normalizedWord = word.toLowerCase();
    const keys: string[] = [];
    for (const key of FEED_QUERY_KEY_LABELS) {
      if (key.startsWith(normalizedWord)) keys.push(key);
    }
    if (keys.length > 0) candidates.push({ word, keys });
  }

  return candidates;
}

function quoteIfNeeded(value: string): string {
  return /\s/.test(value) ? `"${value}"` : value;
}

export function applyFeedQuerySuggestion(
  value: string,
  context: FeedQueryEditContext,
  suggestion: FeedQuerySuggestion,
): { next: string; caret: number; completedKey: boolean } {
  const negation = context.chunk.text.startsWith("-") ? "-" : "";
  const isKey = context.activeKey === null;
  const valuePrefix = context.valueNegated ? "not:" : "";
  const replacement = isKey
    ? `${negation}${suggestion.insert}`
    : `${negation}${context.activeKey}:${valuePrefix}${quoteIfNeeded(suggestion.insert)} `;
  const next =
    value.slice(0, context.chunk.start) +
    replacement +
    value.slice(context.chunk.end);
  return {
    next,
    caret: context.chunk.start + replacement.length,
    completedKey: isKey,
  };
}
