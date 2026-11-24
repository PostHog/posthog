import {
  type CloudRegion,
  getAiGatewayUrl,
  getCloudUrlFromRegion,
  getCustomCloud,
} from "@posthog/agent-contracts";

export const GATEWAY_PRODUCT = "posthog_code";

const PRODUCT_HEADER = "X-PostHog-Product";

export function getGatewayBaseUrl(region: CloudRegion): string {
  return getAiGatewayUrl(
    getCloudUrlFromRegion(region) || getCloudUrlFromRegion("us"),
  );
}

/**
 * The Go gateway has no product route, so a call on the default base names
 * its product in a header. A caller that passes its own base also owns the
 * attribution headers.
 */
export function gatewayHeaders(options: {
  baseUrl?: string;
  headers?: Record<string, string>;
}): Record<string, string> | undefined {
  if (options.baseUrl) return options.headers;
  const named = Object.keys(options.headers ?? {}).some(
    (key) => key.toLowerCase() === PRODUCT_HEADER.toLowerCase(),
  );
  return named
    ? options.headers
    : { [PRODUCT_HEADER]: GATEWAY_PRODUCT, ...options.headers };
}

/**
 * Returns the region only when one was actually configured (an explicit
 * option or a valid `POSTHOG_REGION`), or `undefined` when the caller should
 * decide the region some other way (e.g. prompting interactively at login).
 */
export function resolveExplicitRegion(
  explicit?: CloudRegion,
): CloudRegion | undefined {
  const candidate = explicit ?? process.env.POSTHOG_REGION;
  if (
    candidate === "us" ||
    candidate === "eu" ||
    candidate === "dev" ||
    candidate === "dev-cloud"
  ) {
    return candidate;
  }
  if (candidate === "custom") {
    // A custom region with no target would build every URL from an empty
    // base, so name the missing configuration instead.
    if (!getCustomCloud()) {
      throw new Error(
        "POSTHOG_REGION=custom needs a custom cloud target. Set POSTHOG_CUSTOM_CLOUD_URL (a full https origin) and POSTHOG_CUSTOM_CLOUD_OAUTH_CLIENT_ID.",
      );
    }
    return candidate;
  }
  return undefined;
}

export function resolveRegion(explicit?: CloudRegion): CloudRegion {
  return resolveExplicitRegion(explicit) ?? "us";
}
