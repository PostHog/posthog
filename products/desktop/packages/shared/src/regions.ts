import { customCloudHostLabel, getCustomCloud } from "./custom-cloud";

export const CLOUD_REGIONS = ["us", "eu", "dev", "dev-cloud"] as const;
export type CloudRegion = (typeof CLOUD_REGIONS)[number];

export interface RegionLabel {
  flag: string;
  label: string;
  hint: string;
}

export const REGION_LABELS: Record<CloudRegion, RegionLabel> = {
  us: {
    flag: "🇺🇸",
    label: "US Cloud",
    hint: "us.posthog.com",
  },
  eu: {
    flag: "🇪🇺",
    label: "EU Cloud",
    hint: "eu.posthog.com",
  },
  dev: {
    flag: "🛠️",
    label: "Local development",
    hint: "localhost:8010",
  },
  "dev-cloud": {
    flag: "🧪",
    label: "Dev Cloud",
    hint: "app.dev.posthog.dev",
  },
};

/**
 * The label to show for a region. A configured custom cloud replaces the
 * `dev` label, because that region then points at another instance.
 */
export function describeRegion(region: CloudRegion): RegionLabel {
  if (region !== "dev") return REGION_LABELS[region];
  const custom = getCustomCloud();
  if (!custom) return REGION_LABELS.dev;
  return {
    flag: REGION_LABELS.dev.flag,
    label: "Custom cloud",
    hint: customCloudHostLabel(custom),
  };
}

export function formatRegionBadge(region: CloudRegion): string {
  const entry = describeRegion(region);
  return `${entry.flag} ${entry.label}`;
}
