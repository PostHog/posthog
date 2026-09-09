import { getCustomCloud } from "./custom-cloud";

export const CLOUD_REGIONS = [
  "us",
  "eu",
  "dev",
  "dev-cloud",
  "custom",
] as const;
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
  custom: {
    flag: "🏠",
    label: "Custom",
    hint: "your own instance",
  },
};

export function describeRegion(region: CloudRegion): RegionLabel {
  if (region !== "custom") return REGION_LABELS[region];
  const custom = getCustomCloud();
  if (!custom) return REGION_LABELS.custom;
  return { ...REGION_LABELS.custom, hint: new URL(custom.url).host };
}

export function formatRegionBadge(region: CloudRegion): string {
  const entry = describeRegion(region);
  return `${entry.flag} ${entry.label}`;
}
