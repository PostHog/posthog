// A cloud task's initial prompt may carry the user's saved personalization
// (Settings → Personalization) wrapped in a
// `<user_custom_instructions> ... </user_custom_instructions>` element (see
// buildCustomInstructionsText in @posthog/core). The conversation UI strips that
// element so the raw XML never renders inline in the user's message bubble; these
// helpers detect and pull it out of the stored message text.
//
// The body shown is exactly what was sent in the prompt — parsed from the stored
// event, never re-read from the (possibly newer) live setting.
const CUSTOM_INSTRUCTIONS_REGEX =
  /<user_custom_instructions\b[^>]*>([\s\S]*?)<\/user_custom_instructions>/;

export function hasCustomInstructions(content: string): boolean {
  return CUSTOM_INSTRUCTIONS_REGEX.test(content);
}

// Returns the custom-instructions body plus the message text with the element
// removed (so the user's own request renders cleanly), or null when the content
// has no custom-instructions element.
export function extractCustomInstructions(content: string): {
  body: string;
  stripped: string;
} | null {
  const match = CUSTOM_INSTRUCTIONS_REGEX.exec(content);
  if (match?.index === undefined) return null;

  const body = match[1].trim();
  const stripped = (
    content.slice(0, match.index) + content.slice(match.index + match[0].length)
  ).trim();

  return { body, stripped };
}
