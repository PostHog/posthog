import type { LlmSkillListItem } from "@posthog/api-client/posthog-client";

/**
 * Server-owned classification. Empty for an ordinary team skill; the Signals
 * harness stamps "scout" on the ones it produces.
 */
export function skillCategoryLabel(
  category: string | null | undefined,
): string | null {
  const trimmed = category?.trim();
  if (!trimmed) return null;
  return trimmed
    .split(/[-_\s]+/)
    .map((word) => word.charAt(0).toUpperCase() + word.slice(1))
    .join(" ");
}

/**
 * Version chip text. A skill whose latest version is ahead of the one we
 * fetched says so, since the detail screen always shows the latest.
 */
export function skillVersionLabel(
  skill: Pick<LlmSkillListItem, "version" | "version_count">,
): string {
  const count = skill.version_count ?? 0;
  return count > 1
    ? `v${skill.version} · ${count} versions`
    : `v${skill.version}`;
}

/** Case-insensitive name/description search. An empty query keeps everything. */
export function filterSkills<
  T extends Pick<LlmSkillListItem, "name" | "description">,
>(skills: readonly T[], query: string): T[] {
  const needle = query.trim().toLowerCase();
  if (!needle) return [...skills];
  return skills.filter(
    (skill) =>
      skill.name.toLowerCase().includes(needle) ||
      skill.description?.toLowerCase().includes(needle),
  );
}

/** Alphabetical by name, so the list order does not shift between fetches. */
export function sortSkillsForDisplay<T extends Pick<LlmSkillListItem, "name">>(
  skills: readonly T[],
): T[] {
  return [...skills].sort((a, b) => a.name.localeCompare(b.name));
}
