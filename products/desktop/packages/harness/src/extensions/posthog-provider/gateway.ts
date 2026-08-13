import type { CloudRegion } from "@posthog/shared";

export const GATEWAY_PRODUCT = "posthog_code";

const GATEWAY_HOSTS: Record<CloudRegion, string> = {
  us: "https://gateway.us.posthog.com",
  eu: "https://gateway.eu.posthog.com",
  dev: "http://localhost:3308",
};

export function getGatewayBaseUrl(region: CloudRegion): string {
  return GATEWAY_HOSTS[region];
}

export function getLlmGatewayUrl(region: CloudRegion): string {
  return `${getGatewayBaseUrl(region)}/${GATEWAY_PRODUCT}`;
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
  if (candidate === "us" || candidate === "eu" || candidate === "dev") {
    return candidate;
  }
  return undefined;
}

export function resolveRegion(explicit?: CloudRegion): CloudRegion {
  return resolveExplicitRegion(explicit) ?? "us";
}
