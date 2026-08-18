import type { CommentEmoji } from "@posthog/api-client/posthog-client";
import emojiKeywords from "emojilib";

export interface EmojiSuggestion {
  id: string;
  name: string;
  keywords: string[];
  insertion: string;
  emoji?: string;
  imageUrl?: string;
}

export type EmojiTextSegment =
  | { type: "text"; text: string }
  | { type: "customEmoji"; name: string; url: string };

const MAX_RESULTS = 48;

const standardEmojiSuggestions: EmojiSuggestion[] = Object.entries(
  emojiKeywords,
).map(([emoji, keywords]) => ({
  id: `unicode:${emoji}`,
  name: keywords[0] ?? emoji,
  keywords,
  insertion: emoji,
  emoji,
}));

function matchScore(suggestion: EmojiSuggestion, query: string): number | null {
  const aliases = [suggestion.name, ...suggestion.keywords].map((keyword) =>
    keyword.toLowerCase(),
  );
  const exactIndex = aliases.indexOf(query);
  if (exactIndex >= 0) return exactIndex;
  const prefixIndex = aliases.findIndex((alias) => alias.startsWith(query));
  if (prefixIndex >= 0) return 100 + prefixIndex;
  const inclusionIndex = aliases.findIndex((alias) => alias.includes(query));
  if (inclusionIndex >= 0) return 200 + inclusionIndex;
  return null;
}

export function filterEmojiSuggestions(
  query: string,
  customEmojis: CommentEmoji[],
): EmojiSuggestion[] {
  const normalizedQuery = query
    .replace(/^:+|:+$/g, "")
    .trim()
    .toLowerCase()
    .replaceAll("-", "_");
  if (!normalizedQuery) return [];

  const customSuggestions: EmojiSuggestion[] = customEmojis.map((emoji) => ({
    id: `slack:${emoji.name}`,
    name: emoji.name,
    keywords: [emoji.name],
    insertion: `:${emoji.name}:`,
    imageUrl: emoji.url,
  }));

  return [...customSuggestions, ...standardEmojiSuggestions]
    .map((suggestion) => ({
      suggestion,
      score: matchScore(suggestion, normalizedQuery),
    }))
    .filter(
      (match): match is { suggestion: EmojiSuggestion; score: number } =>
        match.score !== null,
    )
    .sort(
      (left, right) =>
        left.score - right.score ||
        left.suggestion.name.localeCompare(right.suggestion.name),
    )
    .slice(0, MAX_RESULTS)
    .map(({ suggestion }) => suggestion);
}

export function splitCustomEmojiSegments(
  text: string,
  customEmojis: CommentEmoji[],
): EmojiTextSegment[] {
  const emojiByName = new Map(
    customEmojis.map((emoji) => [emoji.name.toLowerCase(), emoji]),
  );
  const segments: EmojiTextSegment[] = [];
  let cursor = 0;

  for (const match of text.matchAll(/:([a-zA-Z0-9_+-]{1,100}):/g)) {
    const start = match.index ?? 0;
    const emoji = emojiByName.get(match[1].toLowerCase());
    if (!emoji) continue;
    if (start > cursor) {
      segments.push({ type: "text", text: text.slice(cursor, start) });
    }
    segments.push({ type: "customEmoji", name: emoji.name, url: emoji.url });
    cursor = start + match[0].length;
  }

  if (cursor < text.length) {
    segments.push({ type: "text", text: text.slice(cursor) });
  }
  return segments.length > 0 ? segments : [{ type: "text", text }];
}
