export const CLOUD_REGIONS = ["us", "eu", "dev", "dev-cloud"] as const;
export type CloudRegion = (typeof CLOUD_REGIONS)[number];

interface RegionLabel {
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

export function formatRegionBadge(region: CloudRegion): string {
  const entry = REGION_LABELS[region];
  return `${entry.flag} ${entry.label}`;
}
