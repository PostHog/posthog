import {
  type CloudRegion,
  getPreviewDeployment,
  REGION_LABELS,
} from "@posthog/shared";

const PRODUCTION_REGIONS: CloudRegion[] = ["us", "eu"];
const DEVELOPMENT_REGIONS: CloudRegion[] = ["dev-cloud", "dev"];

export function getSelectableRegions(
  includeDevRegion: boolean,
  includePreview = getPreviewDeployment() !== null,
): CloudRegion[] {
  return [
    ...(includePreview ? (["preview"] as const) : []),
    ...PRODUCTION_REGIONS,
    ...(includeDevRegion ? DEVELOPMENT_REGIONS : []),
  ];
}

export function describeRegion(region: CloudRegion): {
  flag: string;
  label: string;
  hint: string;
} {
  const preview = region === "preview" ? getPreviewDeployment() : null;
  // The baked SHA names the installed app's build, not the live backend: a
  // backend-only push replaces the backend behind the same installer.
  return preview
    ? {
        ...REGION_LABELS.preview,
        hint: `PR ${preview.prNumber} · app built from ${preview.commitSha.slice(0, 7)}`,
      }
    : REGION_LABELS[region];
}
