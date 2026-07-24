import { type CloudRegion, getCloudUrlFromRegion } from "@posthog/shared";

/**
 * Deep link into the team's own AI observability product. The runner captures
 * the agents' `$ai_*` events into that project, so the trace / generation /
 * cost detail lives there; the observability surface shows lightweight rollups
 * inline and links out here for depth. Returns null until region + project are
 * both known.
 */
export function aiObservabilityTracesUrl(
  region: CloudRegion | null,
  projectId: number | null,
): string | null {
  if (!region || projectId == null) {
    return null;
  }
  return `${getCloudUrlFromRegion(region)}/project/${projectId}/ai-observability/traces`;
}
