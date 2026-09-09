import { getCustomCloud } from "./custom-cloud";
import type { CloudRegion } from "./regions";

const LOCAL_DEV_CLOUD_URL = "http://localhost:8010";

export function getCloudUrlFromRegion(region: CloudRegion): string {
  switch (region) {
    case "us":
      return "https://us.posthog.com";
    case "eu":
      return "https://eu.posthog.com";
    case "dev":
      return getCustomCloud()?.url ?? LOCAL_DEV_CLOUD_URL;
    case "dev-cloud":
      return "https://app.dev.posthog.dev";
  }
}
