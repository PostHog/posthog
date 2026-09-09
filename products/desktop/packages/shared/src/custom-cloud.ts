export interface CustomCloud {
  url: string;
  oauthClientId?: string;
  gatewayUrl?: string;
}

interface BuildEnv {
  env?: Record<string, string | undefined>;
}

function envValue(name: string): string | undefined {
  const runtime =
    typeof process === "undefined" ? undefined : process.env?.[name];
  if (runtime?.trim()) return runtime.trim();
  const build = (import.meta as unknown as BuildEnv).env;
  return build?.[`VITE_${name}`]?.trim() || undefined;
}

function httpUrl(value: string | undefined): string | undefined {
  if (!value) return undefined;
  try {
    const { protocol } = new URL(value);
    if (protocol !== "http:" && protocol !== "https:") return undefined;
  } catch {
    return undefined;
  }
  return value.replace(/\/+$/, "");
}

export function getCustomCloud(): CustomCloud | null {
  const url = httpUrl(envValue("POSTHOG_CUSTOM_CLOUD_URL"));
  if (!url) return null;
  return {
    url,
    oauthClientId: envValue("POSTHOG_CUSTOM_CLOUD_OAUTH_CLIENT_ID"),
    gatewayUrl: httpUrl(envValue("POSTHOG_CUSTOM_CLOUD_GATEWAY_URL")),
  };
}

export function hasCustomCloud(): boolean {
  return getCustomCloud() !== null;
}
