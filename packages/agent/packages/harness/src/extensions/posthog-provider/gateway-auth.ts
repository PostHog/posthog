import type { ExtensionContext } from "@earendil-works/pi-coding-agent";
import { getLlmGatewayUrl, resolveRegion } from "./gateway";
import { POSTHOG_PROVIDER_NAME, type PosthogProviderOptions } from "./provider";

export interface GatewayAuth {
  baseUrl: string;
  apiKey: string;
}

/**
 * Resolves the PostHog LLM gateway base URL and bearer token for callers that
 * need to hit the gateway directly over `fetch`, outside pi's own
 * model-call machinery (e.g. the `web-access` extension's tools).
 *
 * `options.apiKey` (a static override, e.g. for headless use) wins when set.
 * Otherwise this reuses whatever credential the `posthog` provider already
 * has configured — an OAuth access token from `/login`, refreshed
 * automatically by pi, or that provider's own static `apiKey` — resolved
 * fresh on every call so token refresh is picked up automatically. This
 * keeps other gateway callers in sync with `posthog-provider` without
 * duplicating auth.
 */
export async function resolveGatewayAuth(
  options: PosthogProviderOptions,
  ctx: ExtensionContext,
): Promise<GatewayAuth> {
  const region = resolveRegion(options.region);
  const baseUrl = options.baseUrl ?? getLlmGatewayUrl(region);

  const apiKey =
    options.apiKey ??
    (await ctx.modelRegistry.getApiKeyForProvider(POSTHOG_PROVIDER_NAME));

  if (!apiKey) {
    throw new Error(
      'No PostHog gateway credentials available. Run "/login" and choose PostHog, or pass an explicit apiKey.',
    );
  }

  return { baseUrl, apiKey };
}

/**
 * Same as {@link resolveGatewayAuth}, but resolves to `undefined` instead of
 * throwing when no credentials are configured. Use this for tools that can
 * degrade gracefully without gateway access (e.g. web_fetch returning raw
 * markdown instead of a summarized response).
 */
export async function tryResolveGatewayAuth(
  options: PosthogProviderOptions,
  ctx: ExtensionContext,
): Promise<GatewayAuth | undefined> {
  try {
    return await resolveGatewayAuth(options, ctx);
  } catch {
    return undefined;
  }
}
