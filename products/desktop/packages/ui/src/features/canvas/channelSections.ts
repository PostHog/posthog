/**
 * Canonical channel sub-sections shown in the channel header nav
 * ({@link ChannelTabs}) and surfaced as browser-tab names. The `key` is both the
 * route segment (`/spaces/$channelId/<key>`) and the value persisted on a tab's
 * `channelSection`; `label` is the tab + nav text.
 */
export interface ChannelSection {
  key: "loops" | "history" | "context";
  label: string;
}

export const CHANNEL_SECTIONS: readonly ChannelSection[] = [
  { key: "loops", label: "Loops" },
  { key: "history", label: "Recents" },
  // The space's notes are pages now, not a file, and every other surface calls
  // this Context: the page's own title, the breadcrumb, and the sidebar.
  { key: "context", label: "Context" },
] as const;

const BY_KEY = new Map(CHANNEL_SECTIONS.map((s) => [s.key, s]));

/** Resolve a route segment / persisted section value to its display metadata. */
export function channelSectionFor(
  key: string | null | undefined,
): ChannelSection | null {
  return key ? (BY_KEY.get(key as ChannelSection["key"]) ?? null) : null;
}
