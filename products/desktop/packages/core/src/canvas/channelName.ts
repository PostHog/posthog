// A channel's name is used verbatim as its server-side filesystem path segment,
// so it must be directory-safe: lowercase letters, numbers, and hyphens only.
export const CHANNEL_NAME_PATTERN = /^[a-z0-9-]+$/;

// Returns an error message for an invalid name, or null when valid. Empty is
// treated as valid here — callers already gate on a non-empty trimmed value, so
// this validator only judges the character set.
export function validateChannelName(name: string): string | null {
  const trimmed = name.trim();
  if (!trimmed) return null;
  if (!CHANNEL_NAME_PATTERN.test(trimmed)) {
    return "Use only lowercase letters, numbers, and hyphens.";
  }
  return null;
}
