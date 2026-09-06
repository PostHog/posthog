export const SCOUT_DETAIL_TABS = ["activity", "signals", "settings"] as const;

export type ScoutDetailTab = (typeof SCOUT_DETAIL_TABS)[number];
