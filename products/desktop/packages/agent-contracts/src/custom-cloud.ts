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

// A target with no OAuth client ID cannot complete sign-in, and the
// environment path has no form to catch the gap, so the target itself is
// invalid without one.
function normalizeOauthClientId(value: string | undefined): string | undefined {
  const trimmed = value?.trim();
  return trimmed ? trimmed : undefined;
}

// A base URL only. A query, a fragment, or a path would land inside the
// endpoint paths that callers append to it. HTTP is only for loopback hosts,
// because OAuth tokens cross this origin.
function httpUrl(value: string | undefined): string | undefined {
  const trimmed = value?.trim();
  if (!trimmed) return undefined;
  let parsed: URL;
  try {
    parsed = new URL(trimmed);
  } catch {
    return undefined;
  }
  if (
    parsed.protocol !== "https:" &&
    !(parsed.protocol === "http:" && isLoopbackHost(parsed.hostname))
  ) {
    return undefined;
  }
  if (parsed.search || parsed.hash || parsed.pathname !== "/") return undefined;
  return `${parsed.protocol}//${canonicalHost(parsed)}`;
}

function isLoopbackHost(hostname: string): boolean {
  const host = hostname.replace(/\.+$/, "").toLowerCase();
  return host === "localhost" || host === "127.0.0.1" || host === "::1";
}

// A trailing dot in a hostname is a DNS root hint, so `us.posthog.com.` is a
// live alias for US Cloud that an exact-string host set would miss.
function canonicalHost(parsed: URL): string {
  const port = parsed.port ? `:${parsed.port}` : "";
  return `${parsed.hostname.replace(/\.+$/, "")}${port}`;
}

export function normalizeCustomCloud(
  input: Partial<CustomCloud> | null | undefined,
): CustomCloud | null {
  const url = httpUrl(input?.url);
  const oauthClientId = normalizeOauthClientId(input?.oauthClientId);
  // A built-in host would make the region-blind gateway lookups below treat a
  // built-in region as the custom one.
  if (!url || !oauthClientId) return null;
  if (BUILT_IN_HOSTS.has(canonicalHost(new URL(url)))) return null;
  return {
    url,
    oauthClientId,
    gatewayUrl: httpUrl(input?.gatewayUrl),
  };
}

export function isCustomCloudHost(posthogHost: string): boolean {
  const custom = getCustomCloud();
  if (!custom) return false;
  try {
    return (
      canonicalHost(new URL(posthogHost)) === canonicalHost(new URL(custom.url))
    );
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
