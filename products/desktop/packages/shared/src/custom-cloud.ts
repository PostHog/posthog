import { z } from "zod";

export const customCloudSchema = z.object({
  url: z.string(),
  oauthClientId: z.string().optional(),
  gatewayUrl: z.string().optional(),
});

export type CustomCloud = z.infer<typeof customCloudSchema>;

export const CUSTOM_CLOUD_ENV = {
  url: "POSTHOG_CUSTOM_CLOUD_URL",
  oauthClientId: "POSTHOG_CUSTOM_CLOUD_OAUTH_CLIENT_ID",
  gatewayUrl: "POSTHOG_CUSTOM_CLOUD_GATEWAY_URL",
} as const;

function httpUrl(value: string | undefined): string | undefined {
  const trimmed = value?.trim();
  if (!trimmed) return undefined;
  try {
    const { protocol } = new URL(trimmed);
    if (protocol !== "http:" && protocol !== "https:") return undefined;
  } catch {
    return undefined;
  }
  return trimmed.replace(/\/+$/, "");
}

export function normalizeCustomCloud(
  input: Partial<CustomCloud> | null | undefined,
): CustomCloud | null {
  const url = httpUrl(input?.url);
  if (!url) return null;
  return {
    url,
    oauthClientId: input?.oauthClientId?.trim() || undefined,
    gatewayUrl: httpUrl(input?.gatewayUrl),
  };
}

function fromEnv(): CustomCloud | null {
  if (typeof process === "undefined" || !process.env) return null;
  return normalizeCustomCloud({
    url: process.env[CUSTOM_CLOUD_ENV.url],
    oauthClientId: process.env[CUSTOM_CLOUD_ENV.oauthClientId],
    gatewayUrl: process.env[CUSTOM_CLOUD_ENV.gatewayUrl],
  });
}

let configured: CustomCloud | null = null;

export function configureCustomCloud(target: CustomCloud | null): void {
  configured = normalizeCustomCloud(target);
}

export function getCustomCloud(): CustomCloud | null {
  return configured ?? fromEnv();
}

export function hasCustomCloud(): boolean {
  return getCustomCloud() !== null;
}
