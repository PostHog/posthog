/**
 * Serves a session's Claude traffic from Bedrock instead of Anthropic. The
 * `test` variant sends `x-posthog-provider: bedrock`, which the gateway routes
 * to its Bedrock backend; `control` sends nothing and the gateway keeps its
 * `anthropic` default.
 *
 * The variants differ in resilience, not just in provider. `control` keeps the
 * gateway's Bedrock *failover* (`x-posthog-use-bedrock-fallback`), which retries
 * against Bedrock when Anthropic returns 5xx/429 or blocks on billing. `test`
 * cannot use it: the gateway dispatches on the provider header and returns
 * before reading the fallback one, and its direct-Bedrock path has no reverse
 * fallback to Anthropic. So a Bedrock outage fails a `test` session outright.
 *
 * Literal rather than read from the desktop flag registry; flags.test.ts keeps it in step.
 */
export const BEDROCK_LLM_GATEWAY_FLAG = "bedrock-llm-gateway";

/** Variants of {@link BEDROCK_LLM_GATEWAY_FLAG}. */
export const BEDROCK_GATEWAY_VARIANTS = ["test", "control"] as const;

export type BedrockGatewayVariant = (typeof BEDROCK_GATEWAY_VARIANTS)[number];
