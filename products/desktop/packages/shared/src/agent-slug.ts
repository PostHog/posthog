export const AGENT_SLUG_PATTERN = /^[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?$/i;

export function isValidAgentSlug(
  slug: string | null | undefined,
): slug is string {
  return !!slug && AGENT_SLUG_PATTERN.test(slug);
}
