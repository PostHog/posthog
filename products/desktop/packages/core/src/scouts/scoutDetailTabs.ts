export const SCOUT_DETAIL_TABS = ["activity", "signals", "settings"] as const;

export type ScoutDetailTab = (typeof SCOUT_DETAIL_TABS)[number];

export const SCOUT_DETAIL_TAB_LABEL: Record<ScoutDetailTab, string> = {
  activity: "Activity",
  signals: "Signals",
  settings: "Settings",
};

export function isScoutDetailTab(value: unknown): value is ScoutDetailTab {
  return (
    typeof value === "string" &&
    (SCOUT_DETAIL_TABS as readonly string[]).includes(value)
  );
}
