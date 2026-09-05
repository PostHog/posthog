import {
  type AuthDeploymentTarget,
  type CloudRegion,
  isPreviewTarget,
} from "./regions";

/**
 * The API origin for a deployment target. A preview target resolves from its
 * validated manifest and never falls back to an ordinary region; an ordinary
 * region keeps its existing URL. An ordinary region string can never resolve a
 * preview deployment, and a preview manifest can never resolve a production
 * URL.
 */
export function getCloudUrlFromTarget(target: AuthDeploymentTarget): string {
  if (isPreviewTarget(target)) {
    return target.preview.backendOrigin;
  }
  return getCloudUrlFromRegion(target);
}

export function getCloudUrlFromRegion(region: CloudRegion): string {
  switch (region) {
    case "us":
      return "https://us.posthog.com";
    case "eu":
      return "https://eu.posthog.com";
    case "dev":
      return "http://localhost:8010";
    case "dev-cloud":
      return "https://app.dev.posthog.dev";
  }
}
