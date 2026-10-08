import type { CloudRegion } from "@posthog/shared";

const PRODUCTION_REGIONS: CloudRegion[] = ["us", "eu"];
const DEVELOPMENT_REGIONS: CloudRegion[] = ["dev-cloud", "dev"];

export function getSelectableRegions(
  includeDevRegion: boolean,
  includeCustomRegion = false,
): CloudRegion[] {
  return [
    ...PRODUCTION_REGIONS,
    ...(includeDevRegion ? DEVELOPMENT_REGIONS : []),
    ...(includeCustomRegion ? (["custom"] as CloudRegion[]) : []),
  ];
}
