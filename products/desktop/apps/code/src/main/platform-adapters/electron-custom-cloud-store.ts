import type { CustomCloudStore } from "@posthog/core/custom-cloud/identifiers";
import {
  type CustomCloud,
  configureCustomCloud,
  normalizeCustomCloud,
} from "@posthog/shared";
import { settingsStore } from "../services/settingsStore";
import { isCustomCloudBuild } from "../utils/build-channel";

export class ElectronCustomCloudStore implements CustomCloudStore {
  constructor() {
    configureCustomCloud(this.get());
  }

  get(): CustomCloud | null {
    if (!isCustomCloudBuild()) return null;
    return normalizeCustomCloud({
      url: settingsStore.get("customCloudUrl"),
      oauthClientId: settingsStore.get("customCloudOauthClientId"),
      gatewayUrl: settingsStore.get("customCloudGatewayUrl"),
    });
  }

  set(target: CustomCloud | null): CustomCloud | null {
    if (!isCustomCloudBuild()) return null;
    const normalized = normalizeCustomCloud(target);
    settingsStore.set("customCloudUrl", normalized?.url ?? "");
    settingsStore.set(
      "customCloudOauthClientId",
      normalized?.oauthClientId ?? "",
    );
    settingsStore.set("customCloudGatewayUrl", normalized?.gatewayUrl ?? "");
    configureCustomCloud(normalized);
    return normalized;
  }
}
