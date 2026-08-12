/**
 * Canonical channel sub-sections shown in the channel header nav
 * ({@link ChannelTabs}) and surfaced as browser-tab names. The `key` is both the
 * route segment (`/website/$channelId/<key>`) and the value persisted on a tab's
 * `channelSection`; `label` is the tab + nav text.
 */
export interface ChannelSection {
  key: "loops" | "artifacts" | "history" | "context";
  label: string;
}

export const CHANNEL_SECTIONS: readonly ChannelSection[] = [
  { key: "loops", label: "Loops" },
  { key: "artifacts", label: "Artifacts" },
  { key: "history", label: "Recents" },
  { key: "context", label: "CONTEXT.md" },
] as const;

const BY_KEY = new Map(CHANNEL_SECTIONS.map((s) => [s.key, s]));

/** Resolve a route segment / persisted section value to its display metadata. */
export function channelSectionFor(
  key: string | null | undefined,
): ChannelSection | null {
  return key ? (BY_KEY.get(key as ChannelSection["key"]) ?? null) : null;
}
