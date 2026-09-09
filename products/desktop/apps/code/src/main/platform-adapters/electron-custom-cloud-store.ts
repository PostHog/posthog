import type { CustomCloudStore } from "@posthog/core/custom-cloud/identifiers";
import {
  CUSTOM_CLOUD_ENV,
  type CustomCloud,
  configureCustomCloud,
  normalizeCustomCloud,
} from "@posthog/shared";
import { settingsStore } from "../services/settingsStore";
import { decrypt, encrypt } from "../utils/encryption";

export class ElectronCustomCloudStore implements CustomCloudStore {
  constructor() {
    this.apply(this.get());
  }

  get(): CustomCloud | null {
    const encryptedToken = settingsStore.get("customCloudGatewayToken");
    return normalizeCustomCloud({
      url: settingsStore.get("customCloudUrl"),
      oauthClientId: settingsStore.get("customCloudOauthClientId"),
      gatewayUrl: settingsStore.get("customCloudGatewayUrl"),
      gatewayToken: encryptedToken ? (decrypt(encryptedToken) ?? "") : "",
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
    settingsStore.set(
      "customCloudGatewayToken",
      normalized?.gatewayToken ? encrypt(normalized.gatewayToken) : "",
    );
    this.apply(normalized);
    return normalized;
  }

  private apply(target: CustomCloud | null): void {
    configureCustomCloud(target);
    for (const [key, name] of Object.entries(CUSTOM_CLOUD_ENV) as [
      keyof typeof CUSTOM_CLOUD_ENV,
      string,
    ][]) {
      const value = target?.[key];
      if (value) {
        process.env[name] = value;
      } else {
        delete process.env[name];
      }
    }
  }
}
