// Tag names must stay in sync with formatPosthogContextBlock in
// products/posthog_ai/frontend (the web app's AI chat prefixes messages with
// these blocks), the legacy `<posthog_context>` wrapper the backend still
// emits, and the quick-ask panel's PANEL_STEERING.
const POSTHOG_CONTEXT_REGEX =
  /<(posthog_trusted_context|posthog_untrusted_context|posthog_context)\b[^>]*>[\s\S]*?<\/\1>/g;

export function hasPosthogContext(content: string): boolean {
  return new RegExp(POSTHOG_CONTEXT_REGEX.source).test(content);
}

export function extractPosthogContext(content: string): {
  body: string;
  stripped: string;
} | null {
  const blocks = Array.from(
    content.matchAll(POSTHOG_CONTEXT_REGEX),
    (match) => match[0],
  );
  if (blocks.length === 0) return null;

  const stripped = content
    .replace(POSTHOG_CONTEXT_REGEX, "")
    .replace(/\n{3,}/g, "\n\n")
    .trim();

  return { body: blocks.join("\n"), stripped };
}
