import { normalizeChannelName } from "@posthog/core/canvas/channelName";
import type { HomeFeatureFlag } from "@posthog/core/home/homeSchemas";

/** A flag Home offers to turn into a space, and whether that space exists yet. */
export interface HomeFlagSuggestion {
  flag: HomeFeatureFlag;
  /** The space the flag would get, as a channel name. */
  spaceName: string;
  /** The space that already covers this flag, where one does. */
  existingSpace: { id: string; name: string } | null;
}

/** Default number of flags Home offers at once. */
export const HOME_SUGGESTION_LIMIT = 3;

/**
 * The space name a flag would take: `feature-<key>`, without doubling a prefix
 * the key already carries. Normalized the way the create form normalizes it, so
 * the name Home shows is the name the space gets.
 */
export function spaceNameForFlag(flagKey: string): string {
  const normalized = normalizeChannelName(flagKey);
  return normalized.startsWith("feature-")
    ? normalized
    : normalizeChannelName(`feature-${normalized}`);
}

/**
 * Which flags Home offers as work to pick up.
 *
 * A flag driving an experiment is left out — the experiment section says more
 * about it than "you made a flag" does. A flag whose space already exists still
 * shows, because the useful action there is to open that space, and hiding it
 * would make Home quietly forget work already underway.
 */
export function homeFlagSuggestions(input: {
  flags: HomeFeatureFlag[];
  channels: { id: string; name: string }[];
  limit?: number;
}): HomeFlagSuggestion[] {
  const byName = new Map(input.channels.map((c) => [c.name, c.id]));
  const existing = (name: string) => {
    const id = byName.get(name);
    return id ? { id, name } : null;
  };
  return input.flags
    .filter((flag) => !flag.hasExperiment)
    .map((flag) => {
      const spaceName = spaceNameForFlag(flag.key);
      // Either name counts as the flag's space: `feature-checkout` is what Home
      // proposes, but someone who already made `checkout` by hand has one.
      const existingSpace =
        existing(spaceName) ?? existing(normalizeChannelName(flag.key));
      return { flag, spaceName, existingSpace };
    })
    .slice(0, input.limit ?? HOME_SUGGESTION_LIMIT);
}
