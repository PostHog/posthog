import type { CustomCloudStore } from "@posthog/core/custom-cloud/identifiers";
import {
  CUSTOM_CLOUD_ENV,
  type CustomCloud,
  configureCustomCloud,
  normalizeCustomCloud,
} from "@posthog/shared";
import { settingsStore } from "../services/settingsStore";

export class ElectronCustomCloudStore implements CustomCloudStore {
  constructor() {
    this.apply(this.get());
  }

  get(): CustomCloud | null {
    return normalizeCustomCloud({
      url: settingsStore.get("customCloudUrl"),
      oauthClientId: settingsStore.get("customCloudOauthClientId"),
      gatewayUrl: settingsStore.get("customCloudGatewayUrl"),
    });
  }

  set(target: CustomCloud | null): CustomCloud | null {
    const normalized = normalizeCustomCloud(target);
    settingsStore.set("customCloudUrl", normalized?.url ?? "");
    settingsStore.set(
      "customCloudOauthClientId",
      normalized?.oauthClientId ?? "",
    );
    settingsStore.set("customCloudGatewayUrl", normalized?.gatewayUrl ?? "");
    this.apply(normalized);
    return normalized;
  }

  private apply(target: CustomCloud | null): void {
    configureCustomCloud(target);
    const values: Record<keyof CustomCloud, string | undefined> = {
      url: target?.url,
      oauthClientId: target?.oauthClientId,
      gatewayUrl: target?.gatewayUrl,
    };
    for (const key of Object.keys(CUSTOM_CLOUD_ENV) as (keyof CustomCloud)[]) {
      const value = values[key];
      if (value) {
        process.env[CUSTOM_CLOUD_ENV[key]] = value;
      } else {
        delete process.env[CUSTOM_CLOUD_ENV[key]];
      }
    }
  }
}
