import type { Api, Model, OAuthCredentials } from "@earendil-works/pi-ai";
import type {
  AuthStorage,
  ProviderConfig,
  ProviderModelConfig,
} from "@earendil-works/pi-coding-agent";
import type { CloudRegion } from "@posthog/shared";
import {
  getLlmGatewayUrl,
  resolveExplicitRegion,
  resolveRegion,
} from "./gateway";
import { gatewayBaseUrlForApi, resolveModelConfigs } from "./models";
import { loginPosthog, refreshPosthog } from "./oauth";

export const POSTHOG_PROVIDER_NAME = "posthog";

export interface PosthogProviderOptions {
  region?: CloudRegion;
  apiKey?: string;
  baseUrl?: string;
}

export type PosthogOAuthCredentials = Pick<
  OAuthCredentials,
  "access" | "refresh" | "expires"
> & {
  region: CloudRegion;
};

export function parsePosthogOAuthCredentials(
  serialized: string | undefined,
): PosthogOAuthCredentials | null {
  return serialized
    ? (JSON.parse(serialized) as PosthogOAuthCredentials)
    : null;
}

export function setPosthogOAuthCredentials(
  storage: AuthStorage,
  credentials: PosthogOAuthCredentials,
): void {
  storage.set(POSTHOG_PROVIDER_NAME, { type: "oauth", ...credentials });
}

/**
 * Re-routes this provider's already-resolved models to the gateway for the
 * region baked into `credentials` (set at login time). Called by pi whenever
 * it (re)loads models for a provider with stored OAuth credentials, so a
 * user's login region always wins over whatever region the provider was
 * initially registered with.
 */
function remapModelsToCredentialRegion(
  models: Model<Api>[],
  credentials: OAuthCredentials,
  fallbackRegion: CloudRegion,
  baseUrl?: string,
): Model<Api>[] {
  const region =
    (credentials.region as CloudRegion | undefined) ?? fallbackRegion;
  return models.map((model) =>
    model.provider === POSTHOG_PROVIDER_NAME
      ? {
          ...model,
          baseUrl: gatewayBaseUrlForApi(model.api, region, baseUrl),
        }
      : model,
  );
}

export function buildPosthogProvider(
  models: ProviderModelConfig[],
  options: PosthogProviderOptions = {},
): ProviderConfig {
  const region = resolveRegion(options.region);
  const explicitRegion = resolveExplicitRegion(options.region);
  const baseUrl = options.baseUrl ?? getLlmGatewayUrl(region);
  const routedModels = models.map((model) => ({
    ...model,
    baseUrl: gatewayBaseUrlForApi(
      model.api ?? "anthropic-messages",
      region,
      baseUrl,
    ),
  }));
  const config: ProviderConfig = {
    name: "PostHog",
    baseUrl,
    api: "anthropic-messages",
    models: routedModels,
    oauth: {
      name: "PostHog",
      login: (callbacks) => loginPosthog(callbacks, explicitRegion),
      refreshToken: (credentials) => refreshPosthog(region, credentials),
      getApiKey: (credentials) => String(credentials.access),
      modifyModels: (models, credentials) =>
        remapModelsToCredentialRegion(
          models,
          credentials,
          region,
          options.baseUrl,
        ),
    },
  };
  if (options.apiKey) {
    config.apiKey = options.apiKey;
  }
  return config;
}

export async function resolvePosthogProvider(
  options: PosthogProviderOptions = {},
): Promise<ProviderConfig> {
  const region = resolveRegion(options.region);
  const models = await resolveModelConfigs(
    region,
    options.baseUrl,
    options.apiKey,
  );
  return buildPosthogProvider(models, options);
}
