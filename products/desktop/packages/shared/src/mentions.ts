/**
 * @-mention tokens embedded in channel thread message content.
 *
 * Mentions are stored inline as `@[Display Name](email)` so the plain string
 * survives every transport/storage layer unchanged, older clients degrade to
 * readable text, and any client can render mentions as chips from the content
 * alone. The backend indexes the same tokens at write time to serve the
 * mentions feed (`getTaskMentions`).
 */

// `@` is excluded on both sides of the separator so the match point is
// unambiguous — with it allowed, adversarial input backtracks quadratically
// (CodeQL js/polynomial-redos). Real emails carry exactly one `@` anyway.
const MENTION_PATTERN = /@\[([^\][\n]+)\]\(([^\s()@]+@[^\s()@]+)\)/g;

export interface MentionTextSegment {
  type: "text";
  text: string;
}

export interface MentionUserSegment {
  type: "mention";
  /** The raw token as it appears in the content. */
  text: string;
  name: string;
  email: string;
}

export type MentionSegment = MentionTextSegment | MentionUserSegment;

/** Serialize a user reference into the inline mention token. */
export function formatMention(name: string, email: string): string {
  // Brackets and newlines would break token parsing; email is the identity so
  // it falls back to the local part when the display name is unusable.
  const safeName =
    name.replace(/[[\]\n]/g, " ").trim() || email.split("@")[0] || email;
  return `@[${safeName}](${email})`;
}

/** Split content into text and mention segments, in document order. */
export function splitMentionSegments(content: string): MentionSegment[] {
  const segments: MentionSegment[] = [];
  let lastIndex = 0;
  MENTION_PATTERN.lastIndex = 0;
  for (const match of content.matchAll(MENTION_PATTERN)) {
    const index = match.index ?? 0;
    if (index > lastIndex) {
      segments.push({ type: "text", text: content.slice(lastIndex, index) });
    }
    segments.push({
      type: "mention",
      text: match[0],
      name: match[1] ?? "",
      email: match[2] ?? "",
    });
    lastIndex = index + match[0].length;
  }
  if (lastIndex < content.length) {
    segments.push({ type: "text", text: content.slice(lastIndex) });
  }
  return segments;
}

/** Content with mention tokens flattened to `@Display Name` for plain surfaces. */
export function mentionsToPlainText(content: string): string {
  return splitMentionSegments(content)
    .map((segment) =>
      segment.type === "mention" ? `@${segment.name}` : segment.text,
    )
    .join("");
}
