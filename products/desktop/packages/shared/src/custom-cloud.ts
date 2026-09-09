/**
 * The custom PostHog instance that the `dev` region points at.
 *
 * With no configuration the `dev` region keeps its local defaults. A private
 * image, or a shell that sets the environment variables, can point that one
 * region at a self-hosted PostHog instead. The `us`, `eu`, and `dev-cloud`
 * regions never read this, so a shipped build stays on PostHog Cloud.
 */
export interface CustomCloud {
  /** Base URL of the instance, for example `https://posthog.example.com`. */
  url: string;
  /** Client ID of the OAuth application on that instance. */
  oauthClientId?: string;
  /** Base URL of the LLM gateway that serves that instance. */
  gatewayUrl?: string;
}

/**
 * Each value has a plain name for a runtime environment, and a `VITE_` name
 * for the build, because Vite only gives prefixed values to the app.
 */
const CUSTOM_CLOUD_URL_ENV_NAMES = [
  "POSTHOG_CUSTOM_CLOUD_URL",
  "VITE_POSTHOG_CUSTOM_CLOUD_URL",
] as const;
const CUSTOM_CLOUD_OAUTH_CLIENT_ID_ENV_NAMES = [
  "POSTHOG_CUSTOM_CLOUD_OAUTH_CLIENT_ID",
  "VITE_POSTHOG_CUSTOM_CLOUD_OAUTH_CLIENT_ID",
] as const;
const CUSTOM_CLOUD_GATEWAY_URL_ENV_NAMES = [
  "POSTHOG_CUSTOM_CLOUD_GATEWAY_URL",
  "VITE_POSTHOG_CUSTOM_CLOUD_GATEWAY_URL",
] as const;

type EnvSource = Record<string, string | undefined>;

function firstValue(
  env: EnvSource,
  names: readonly string[],
): string | undefined {
  for (const name of names) {
    const value = env[name]?.trim();
    if (value) return value;
  }
  return undefined;
}

function normalizeHttpUrl(candidate: string | undefined): string | undefined {
  if (!candidate) return undefined;
  let parsed: URL;
  try {
    parsed = new URL(candidate);
  } catch {
    return undefined;
  }
  if (parsed.protocol !== "http:" && parsed.protocol !== "https:") {
    return undefined;
  }
  return candidate.replace(/\/+$/, "");
}

/** Reads a target from an environment. Returns null when no URL is set. */
export function readCustomCloudFromEnv(env: EnvSource): CustomCloud | null {
  const url = normalizeHttpUrl(firstValue(env, CUSTOM_CLOUD_URL_ENV_NAMES));
  if (!url) return null;
  return {
    url,
    oauthClientId: firstValue(env, CUSTOM_CLOUD_OAUTH_CLIENT_ID_ENV_NAMES),
    gatewayUrl: normalizeHttpUrl(
      firstValue(env, CUSTOM_CLOUD_GATEWAY_URL_ENV_NAMES),
    ),
  };
}

let configured: CustomCloud | null = null;

/**
 * Sets the target that this process uses. The renderer must call this, because
 * it has no `process.env`. `null` gives the environment back as the source.
 */
export function configureCustomCloud(target: CustomCloud | null): void {
  if (!target) {
    configured = null;
    return;
  }
  const url = normalizeHttpUrl(target.url);
  configured = url ? { ...target, url } : null;
}

export function getCustomCloud(): CustomCloud | null {
  if (configured) return configured;
  // Node processes (main, workspace server, agent server, tests) read the
  // environment here, so each entry point does not have to inject the value.
  const env = typeof process === "undefined" ? undefined : process.env;
  return env ? readCustomCloudFromEnv(env) : null;
}

export function hasCustomCloud(): boolean {
  return getCustomCloud() !== null;
}

/** Host of the target, for a label. Falls back to the raw URL. */
export function customCloudHostLabel(target: CustomCloud): string {
  try {
    return new URL(target.url).host;
  } catch {
    return target.url;
  }
}
