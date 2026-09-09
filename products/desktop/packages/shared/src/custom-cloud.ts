import { z } from "zod";

export const customCloudSchema = z.object({
  url: z.string(),
  oauthClientId: z.string().optional(),
  gatewayUrl: z.string().optional(),
});

export type CustomCloud = z.infer<typeof customCloudSchema>;

const BUILT_IN_HOSTS = new Set([
  "us.posthog.com",
  "eu.posthog.com",
  "app.dev.posthog.dev",
  "localhost:8010",
]);

// A base URL only. A query, a fragment, or a path would land inside the
// endpoint paths that callers append to it.
function httpUrl(value: string | undefined): string | undefined {
  const trimmed = value?.trim();
  if (!trimmed) return undefined;
  let parsed: URL;
  try {
    parsed = new URL(trimmed);
  } catch {
    return undefined;
  }
  if (parsed.protocol !== "http:" && parsed.protocol !== "https:") {
    return undefined;
  }
  if (parsed.search || parsed.hash || parsed.pathname !== "/") return undefined;
  return `${parsed.protocol}//${parsed.host}`;
}

export function normalizeCustomCloud(
  input: Partial<CustomCloud> | null | undefined,
): CustomCloud | null {
  const url = httpUrl(input?.url);
  // A built-in host would make the region-blind gateway lookups below treat a
  // built-in region as the custom one.
  if (!url || BUILT_IN_HOSTS.has(new URL(url).host)) return null;
  return {
    url,
    oauthClientId: input?.oauthClientId?.trim() || undefined,
    gatewayUrl: httpUrl(input?.gatewayUrl),
  };
}

export function isCustomCloudHost(posthogHost: string): boolean {
  const custom = getCustomCloud();
  if (!custom) return false;
  try {
    return new URL(posthogHost).host === new URL(custom.url).host;
  } catch {
    return false;
  }
}

function fromEnv(): CustomCloud | null {
  if (typeof process === "undefined" || !process.env) return null;
  return normalizeCustomCloud({
    url: process.env.POSTHOG_CUSTOM_CLOUD_URL,
    oauthClientId: process.env.POSTHOG_CUSTOM_CLOUD_OAUTH_CLIENT_ID,
    gatewayUrl: process.env.POSTHOG_CUSTOM_CLOUD_GATEWAY_URL,
  });
}

let configured: CustomCloud | null = null;

// Every path funnels through here, so this is where a value that the rules
// refuse has to be dropped.
export function configureCustomCloud(target: CustomCloud | null): void {
  configured = normalizeCustomCloud(target);
}

export function getCustomCloud(): CustomCloud | null {
  return configured ?? fromEnv();
}
