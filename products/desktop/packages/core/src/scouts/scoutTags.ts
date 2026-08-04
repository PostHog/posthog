import type { ScoutConfig } from "@posthog/api-client/posthog-client";

/**
 * Scout tags: lowercase kebab-case labels for grouping the fleet ("revenue",
 * "on-call"). Mirrors the server's normalization (`scout_harness/tags.py`) so
 * the editor shows the tag that will actually be stored rather than what was
 * typed, and mirrors its caps so the input can refuse before the PATCH does.
 */
export const MAX_SCOUT_TAGS = 10;
export const MAX_SCOUT_TAG_LENGTH = 50;

/** Lowercase kebab-case slug for one tag, or "" if nothing survives. */
export function normalizeScoutTag(raw: string): string {
  return raw
    .trim()
    .toLowerCase()
    .replace(/[\s_]+/g, "-")
    .replace(/[^a-z0-9-]+/g, "")
    .replace(/-{2,}/g, "-")
    .replace(/^-+|-+$/g, "");
}

export interface ParsedScoutTags {
  tags: string[];
  /**
   * Entries over `MAX_SCOUT_TAG_LENGTH`. Reported rather than dropped so the
   * editor can say the tag didn't take instead of silently swallowing it.
   */
  tooLong: string[];
}

/**
 * Parse what someone typed into the tag box. Commas separate, so a pasted
 * "revenue, on call" lands as two tags rather than one malformed one. Entries
 * that normalize to nothing are noise (a stray trailing comma) and are dropped
 * silently; over-long ones are not.
 */
export function parseScoutTagsInput(input: string): ParsedScoutTags {
  const tags: string[] = [];
  const tooLong: string[] = [];
  for (const candidate of input.split(",")) {
    const tag = normalizeScoutTag(candidate);
    if (!tag) continue;
    if (tag.length > MAX_SCOUT_TAG_LENGTH) tooLong.push(tag);
    else if (!tags.includes(tag)) tags.push(tag);
  }
  return { tags, tooLong };
}

/** The tags on a config, tolerating a backend that predates the field. */
export function scoutTags(config: ScoutConfig): string[] {
  return config.tags ?? [];
}

/**
 * Add tags to a scout's existing set, returning the full replacement list the
 * API expects. Sorted to match the stored order, so a no-op edit stays a no-op.
 * Returns null when nothing would change or the cap is already reached — the
 * caller skips the request rather than sending an edit that does nothing.
 */
export function withScoutTagsAdded(
  existing: string[],
  additions: string[],
): string[] | null {
  const next = new Set(existing);
  for (const tag of additions) {
    if (next.size >= MAX_SCOUT_TAGS) break;
    next.add(tag);
  }
  if (next.size === existing.length) return null;
  return [...next].sort();
}

/** Remove one tag, returning the full replacement list, or null if absent. */
export function withScoutTagRemoved(
  existing: string[],
  tag: string,
): string[] | null {
  if (!existing.includes(tag)) return null;
  return existing.filter((candidate) => candidate !== tag).sort();
}

export interface ScoutTagOption {
  tag: string;
  /** How many scouts in the fleet carry it, so the picker can show weight. */
  count: number;
}

/**
 * Every tag in use across the fleet, most-used first then alphabetical — the
 * option list for the fleet filter. Derived from the loaded configs rather than
 * fetched: the whole fleet is already in hand, and an org's scout count is
 * capped well below where that would matter.
 */
export function listScoutTagOptions(configs: ScoutConfig[]): ScoutTagOption[] {
  const counts = new Map<string, number>();
  for (const config of configs) {
    for (const tag of scoutTags(config)) {
      counts.set(tag, (counts.get(tag) ?? 0) + 1);
    }
  }
  return [...counts.entries()]
    .map(([tag, count]) => ({ tag, count }))
    .sort((a, b) => b.count - a.count || a.tag.localeCompare(b.tag));
}

/**
 * Any-of, matching the server's `tags__overlap` filter: selecting two tags
 * widens the list rather than narrowing it to scouts carrying both.
 */
export function configMatchesScoutTags(
  config: ScoutConfig,
  selected: string[],
): boolean {
  if (selected.length === 0) return true;
  const tags = scoutTags(config);
  return selected.some((tag) => tags.includes(tag));
}
