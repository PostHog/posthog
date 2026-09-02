import { unescapeXmlAttr } from "@posthog/shared";

// The agent's initial prompt may carry a channel's CONTEXT.md wrapped in a
// `<channel_context channel="name"> ... </channel_context>` element (see
// buildChannelContextBlock in @posthog/core). The conversation UI collapses
// that element into a single clickable tag instead of rendering the whole body
// inline, so these helpers detect and pull it out of the stored message text.
//
// The body shown is exactly what was sent in the prompt — parsed from the
// stored event, never re-fetched from the (possibly newer) live CONTEXT.md.
const CHANNEL_CONTEXT_REGEX =
  /<channel_context\b([^>]*)>([\s\S]*?)<\/channel_context>/;

export interface ChannelContextMention {
  /** Channel display name, or null when the prompt didn't carry one. */
  name: string | null;
  /** The exact text that was sent inside the element. */
  body: string;
}

export function hasChannelContext(content: string): boolean {
  return CHANNEL_CONTEXT_REGEX.test(content);
}

// Returns the parsed channel-context mention plus the message text with the
// element removed (so the user's own prompt renders cleanly), or null when the
// content has no channel-context element.
export function extractChannelContext(content: string): {
  mention: ChannelContextMention;
  stripped: string;
} | null {
  const match = CHANNEL_CONTEXT_REGEX.exec(content);
  if (match?.index === undefined) return null;

  const attrs = match[1] ?? "";
  const nameMatch = /channel="([^"]*)"/.exec(attrs);
  const name = nameMatch ? unescapeXmlAttr(nameMatch[1]) : null;
  const body = match[2].trim();
  const stripped = (
    content.slice(0, match.index) + content.slice(match.index + match[0].length)
  ).trim();

  return { mention: { name, body }, stripped };
}
