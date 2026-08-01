import { getCloudTaskGatewayUrl } from "@posthog/shared";

export type GatewayProduct =
  | "posthog_code"
  | "background_agents"
  | "signals"
  | "slack_app"
  | "posthog_ai"
  | "conversations"
  | "onboarding";

export function resolveGatewayProduct({
  isInternal,
  originProduct,
}: {
  isInternal?: boolean;
  originProduct?: string | null;
} = {}): GatewayProduct {
  const originProductToGatewayProductMap: Record<string, GatewayProduct> = {
    loop: "posthog_code",
    onboarding: "onboarding",
    posthog_ai: "posthog_ai",
    signal_report: "signals",
    signals_scout: "signals",
    slack: "slack_app",
    support_reply: "conversations",
  };

  if (originProduct && originProduct in originProductToGatewayProductMap) {
    return originProductToGatewayProductMap[originProduct];
  }
  if (isInternal) {
    return "background_agents";
  }
  return "posthog_code";
}

export {
  buildPosthogPropertiesHeaderLines as buildGatewayPropertiesHeader,
  buildPosthogPropertiesHeaderRecord as buildGatewayPropertiesHeaderRecord,
  buildPosthogPropertyHeaderLines as buildGatewayPropertyHeaders,
  buildPosthogPropertyHeaderRecord as buildGatewayPropertyHeaderRecord,
} from "@posthog/shared/posthog-property-headers";

function getGatewayBaseUrl(posthogHost: string): string {
  return getCloudTaskGatewayUrl(posthogHost).replace(/\/posthog_code$/, "");
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
  { slugless = false }: { slugless?: boolean } = {},
): string {
  if (slugless) {
    // The Go gateway routes by credential and header, not path, so the product
    // slug would 404. A trailing `/v1` is stripped because callers re-append
    // it: the Anthropic SDK adds `/v1/messages`, and the OpenAI base URL is
    // derived by appending `/v1`.
    const base = (envUrl ?? getGatewayBaseUrl(posthogHost)).replace(/\/+$/, "");
    return base.replace(/\/v1$/, "");
  }
  if (envUrl) {
    return `${envUrl.replace(/\/$/, "")}/${product}`;
  }
  return getLlmGatewayUrl(posthogHost, product);
}

/** Products routed to the Go gateway, from a comma-separated env value. */
function parseAiGatewayProducts(raw: string | undefined): Set<string> {
  return new Set(
    (raw ?? "")
      .split(",")
      .map((entry) => entry.trim())
      .filter(Boolean),
  );
}

/**
 * Sandbox-run signals stages, which are billed per stage rather than under one
 * `signals` product. The stage names come from `TaskRun.state.ai_stage`, set in
 * `Task._build_task` in posthog/posthog.
 */
const SIGNALS_STAGE_PRODUCTS = new Set([
  "scout",
  "research",
  "implementation",
  "repo_selection",
]);

/**
 * The `ai_product` value sent to the Go gateway, which has no product route and
 * so cannot infer it from the path.
 *
 * Signals splits per stage (`signals_scout`), matching the `signals_grouping` /
 * `signals_emission` tags its non-sandbox stages already emit. Every other
 * product keeps its existing name so its dashboards stay continuous across the
 * cutover.
 */
export function resolveAiProduct({
  product,
  aiStage,
}: {
  product: GatewayProduct;
  aiStage?: string | null;
}): string {
  if (product === "signals" && aiStage && SIGNALS_STAGE_PRODUCTS.has(aiStage)) {
    return `signals_${aiStage}`;
  }
  return product;
}

export function getGatewayUsageUrl(
  posthogHost: string,
  product: GatewayProduct = "posthog_code",
): string {
  return `${getGatewayBaseUrl(posthogHost)}/v1/usage/${product}`;
}

export interface GatewayTarget {
  /** Base URL: slugless for the Go gateway, product-slugged for the Python one. */
  baseUrl: string;
  /** True when the Go gateway is selected, which also changes the header format. */
  isAiGateway: boolean;
  /** Product tag; only the Go gateway needs it sent explicitly. */
  aiProduct: string;
}

/**
 * Choose which gateway a request targets.
 *
 * The two gateways run on separate hosts (`ai-gateway.*` vs `gateway.*`), so
 * the base URL is what distinguishes them. `AI_GATEWAY_URL` selects the Go
 * gateway, and `AI_GATEWAY_PRODUCTS` limits that to named products so one
 * product can migrate without moving every other caller sharing this server.
 *
 * Both must be set: an unlisted product, or a listed one with no URL, stays on
 * the Python gateway. Migration is therefore opt-in per product, and clearing
 * either value rolls everything back.
 */
export function resolveGatewayTarget({
  product,
  aiStage,
  posthogHost,
  env = process.env,
}: {
  product: GatewayProduct;
  aiStage?: string | null;
  posthogHost: string;
  env?: Record<string, string | undefined>;
}): GatewayTarget {
  const aiProduct = resolveAiProduct({ product, aiStage });
  const aiGatewayUrl = (env.AI_GATEWAY_URL ?? "").trim();
  const routed =
    aiGatewayUrl !== "" &&
    parseAiGatewayProducts(env.AI_GATEWAY_PRODUCTS).has(aiProduct);

  if (routed) {
    return {
      baseUrl: resolveLlmGatewayUrl(aiGatewayUrl, posthogHost, product, {
        slugless: true,
      }),
      isAiGateway: true,
      aiProduct,
    };
  }
  return {
    baseUrl: resolveLlmGatewayUrl(env.LLM_GATEWAY_URL, posthogHost, product),
    isAiGateway: false,
    aiProduct,
  };
}
