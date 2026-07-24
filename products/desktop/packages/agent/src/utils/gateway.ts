export type GatewayProduct =
  | "posthog_code"
  | "background_agents"
  | "signals"
  | "slack_app"
  | "posthog_ai"
  | "conversations";

export function resolveGatewayProduct({
  isInternal,
  originProduct,
}: {
  isInternal?: boolean;
  originProduct?: string | null;
} = {}): GatewayProduct {
  if (originProduct === "slack") {
    return "slack_app";
  }
  if (originProduct === "posthog_ai") {
    return "posthog_ai";
  }
  if (originProduct === "signal_report" || originProduct === "signals_scout") {
    return "signals";
  }
  if (originProduct === "support_reply") {
    return "conversations";
  }
  if (isInternal) {
    return "background_agents";
  }
  return "posthog_code";
}

export {
  buildPosthogPropertyHeaderLines as buildGatewayPropertyHeaders,
  buildPosthogPropertyHeaderRecord as buildGatewayPropertyHeaderRecord,
} from "@posthog/shared/posthog-property-headers";

function getGatewayBaseUrl(posthogHost: string): string {
  const url = new URL(posthogHost);
  const hostname = url.hostname;

  if (hostname === "localhost" || hostname === "127.0.0.1") {
    return `${url.protocol}//localhost:3308`;
  }

  if (hostname === "host.docker.internal") {
    return `${url.protocol}//host.docker.internal:3308`;
  }

  // The hosted dev environment runs its own LLM gateway with its own auth DB,
  // so a dev-minted `pha_` token can't be routed to the US gateway — that's
  // a different DB and returns 401 Authentication required.
  if (hostname === "app.dev.posthog.dev") {
    return "https://gateway.dev.posthog.dev";
  }

  const region = hostname.match(/^(us|eu)\.posthog\.com$/)?.[1] ?? "us";
  return `https://gateway.${region}.posthog.com`;
}

export function getLlmGatewayUrl(
  posthogHost: string,
  product: GatewayProduct = "posthog_code",
): string {
  return `${getGatewayBaseUrl(posthogHost)}/${product}`;
}

/**
 * Resolve the gateway URL for a request, preferring an explicit
 * `LLM_GATEWAY_URL` override over the region-aware default. The override is
 * treated as a *base* URL — the product slug is always appended so the gateway
 * can route to the correct product config. Without this, a bare-host override
 * (e.g. `https://gateway.dev.posthog.dev`) lost the product suffix and every
 * request fell into the catch-all `llm_gateway` product which OAuth tokens
 * cannot use (403).
 */
export function resolveLlmGatewayUrl(
  envUrl: string | undefined,
  posthogHost: string,
  product: GatewayProduct = "posthog_code",
): string {
  if (envUrl) {
    return `${envUrl.replace(/\/$/, "")}/${product}`;
  }
  return getLlmGatewayUrl(posthogHost, product);
}

export function getGatewayUsageUrl(
  posthogHost: string,
  product: GatewayProduct = "posthog_code",
): string {
  return `${getGatewayBaseUrl(posthogHost)}/v1/usage/${product}`;
}
