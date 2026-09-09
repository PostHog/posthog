import type { CustomCloudStore } from "@posthog/core/custom-cloud/identifiers";
import {
  type CustomCloud,
  configureCustomCloud,
  normalizeCustomCloud,
} from "@posthog/shared";
import { settingsStore } from "../services/settingsStore";
import { decrypt, encrypt } from "../utils/encryption";

export class ElectronCustomCloudStore implements CustomCloudStore {
  constructor() {
    configureCustomCloud(this.get());
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
    configureCustomCloud(normalized);
    return normalized;
  }
}
