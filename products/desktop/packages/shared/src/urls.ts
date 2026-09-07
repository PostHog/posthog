import { requirePreviewDeployment } from "./desktop-preview";
import type { CloudRegion } from "./regions";

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
    case "preview":
      return requirePreviewDeployment().backendOrigin;
  }
}
