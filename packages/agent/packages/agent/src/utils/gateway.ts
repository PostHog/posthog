import { getCloudTaskGatewayUrl } from "@posthog/agent-contracts";

export const GATEWAY_PRODUCTS = [
  "posthog_code",
  "background_agents",
  "signals",
  "slack_app",
  "workflows",
  "posthog_ai",
  "conversations",
  "account_audit",
  "autoresearch",
  "onboarding",
  "review_hog",
] as const;

export type GatewayProduct = (typeof GATEWAY_PRODUCTS)[number];

export function fallbackGatewayProduct(isInternal = false): GatewayProduct {
  return isInternal ? "background_agents" : "posthog_code";
}

export function getAiGatewayUrl(posthogHost: string): string {
  return getCloudTaskGatewayUrl(posthogHost);
}

/**
 * Strips a trailing `/v1` because callers re-append it: the Anthropic SDK adds
 * `/v1/messages`, and the OpenAI base URL appends `/v1`.
 */
export function resolveAiGatewayBaseUrl(
  envUrl: string | undefined,
  posthogHost: string,
): string {
  const base = (envUrl || getAiGatewayUrl(posthogHost)).replace(/\/+$/, "");
  return base.replace(/\/v1$/, "");
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
 * `Task._build_task` (pipeline stages) and `Task.create_run` (interactive
 * `inbox` / `chat`) in posthog/posthog.
 */
const SIGNALS_STAGE_PRODUCTS = new Set([
  "scout",
  "research",
  "implementation",
  "repo_selection",
  "custom_agent",
  "inbox",
  "chat",
  "scout_suggestions",
]);

/**
 * Scout runs qualify their stage with the skill (`scout:web-analytics`) for
 * per-scout cost attribution. The product stays `signals_scout`.
 */
const SCOUT_STAGE_PREFIX = "scout:";

function signalsStage(aiStage: string): string {
  return aiStage.startsWith(SCOUT_STAGE_PREFIX) ? "scout" : aiStage;
}

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
  if (product === "signals" && aiStage) {
    const stage = signalsStage(aiStage);
    if (SIGNALS_STAGE_PRODUCTS.has(stage)) {
      return `signals_${stage}`;
    }
  }
  return product;
}

export interface GatewayTarget {
  /** Go gateway base URL, with no product slug. */
  baseUrl: string;
  /** True when `AI_GATEWAY_URL` is set and `AI_GATEWAY_PRODUCTS` lists the product. */
  routed: boolean;
  /** Product tag, sent explicitly because the gateway has no product route. */
  aiProduct: string;
  /** Stage the product was resolved from: the worker's, else the caller's, else none. */
  aiStage: string | null;
}

/**
 * A run is routed only when `AI_GATEWAY_URL` is set and `AI_GATEWAY_PRODUCTS`
 * lists its product. The worker sets both, and mints a token, only for
 * products it routes, so an unrouted run has no way to reach a model.
 *
 * Scout entries may qualify by skill (`signals_scout:web-analytics`), matching
 * only runs of that skill. A plain `signals_scout` entry matches every skill.
 *
 * `AI_GATEWAY_PRODUCT` and `AI_GATEWAY_AI_STAGE` name the product the worker pinned the token
 * to. They win over the local derivation, whose task-run fetch can fail and leave no stage.
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
  const workerStage = (env.AI_GATEWAY_AI_STAGE ?? "").trim() || null;
  const workerProduct = (env.AI_GATEWAY_PRODUCT ?? "").trim() || null;
  const effectiveStage = workerStage ?? aiStage ?? null;
  const aiProduct =
    workerProduct ?? resolveAiProduct({ product, aiStage: effectiveStage });
  const aiGatewayUrl = (env.AI_GATEWAY_URL ?? "").trim();
  const routedProducts = parseAiGatewayProducts(env.AI_GATEWAY_PRODUCTS);
  const skillQualified = effectiveStage?.startsWith(SCOUT_STAGE_PREFIX)
    ? `${aiProduct}:${effectiveStage.slice(SCOUT_STAGE_PREFIX.length)}`
    : null;
  const routed =
    aiGatewayUrl !== "" &&
    (routedProducts.has(aiProduct) ||
      (skillQualified !== null && routedProducts.has(skillQualified)));

  return {
    baseUrl: resolveAiGatewayBaseUrl(aiGatewayUrl, posthogHost),
    routed,
    aiProduct,
    aiStage: effectiveStage,
  };
}

/** The Go gateway has no `@cf/` alias, so a saved Cloudflare id loses its prefix. */
export function modelIdForGatewayRoute<T extends string | undefined>(
  model: T,
): T {
  return model?.replace(/^@cf\//, "") as T;
}
