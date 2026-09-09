import { getLlmGatewayUrl } from "@posthog/agent/posthog-api";
import type { AuthService } from "@posthog/core/auth/auth";
import { customCloudGatewayToken } from "@posthog/shared";

function isGatewayUrl(url: string, apiHost: string): boolean {
  try {
    return new URL(url).origin === new URL(getLlmGatewayUrl(apiHost)).origin;
  } catch {
    return false;
  }
}

// The gateway of another instance does not know the session token, so the
// custom gateway token replaces it there, and only there.
export function createGatewayAwareFetch(
  auth: () => AuthService,
): (url: string, init?: RequestInit) => Promise<Response> {
  return async (url, init = {}) => {
    const { apiHost } = await auth().getValidAccessToken();
    const token = customCloudGatewayToken(apiHost);
    if (token && isGatewayUrl(url, apiHost)) {
      const headers = new Headers(init.headers);
      headers.set("authorization", `Bearer ${token}`);
      return fetch(url, { ...init, headers });
    }
    return auth().authenticatedFetch(fetch, url, init);
  };
}
