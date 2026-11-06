export const SCOUT_DETAIL_TABS = ["activity", "output", "settings"] as const;

export type ScoutDetailTab = (typeof SCOUT_DETAIL_TABS)[number];
