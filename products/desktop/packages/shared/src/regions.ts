import type { DesktopPreviewManifest } from "./desktop-preview";

/**
 * Deployment targets for the PostHog API client. The four `CloudRegion` values
 * are ordinary deployments with fixed URLs and OAuth client ids. `preview` is
 * the desktop-preview deployment: an isolated backend whose origin and OAuth
 * client id come from a validated build-time manifest, so it carries the
 * manifest with it everywhere a region value flows.
 */
export const CLOUD_REGIONS = ["us", "eu", "dev", "dev-cloud"] as const;
export type CloudRegion = (typeof CLOUD_REGIONS)[number];

export type AuthDeploymentTarget =
  | CloudRegion
  | { preview: DesktopPreviewManifest };

export function isPreviewTarget(
  target: AuthDeploymentTarget,
): target is { preview: DesktopPreviewManifest } {
  return typeof target !== "string";
}

/** The ordinary-region part of a target; `"preview"` for preview deployments. */
export function targetRegionKey(
  target: AuthDeploymentTarget,
): CloudRegion | "preview" {
  return typeof target === "string" ? target : "preview";
}

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
