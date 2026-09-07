import featureFlagKeys from "./feature-flag-keys.json" with { type: "json" };

export const BILLING_FLAG = featureFlagKeys.BILLING_FLAG;
export const CLOUD_COMPUTE_BILLING_FLAG =
  featureFlagKeys.CLOUD_COMPUTE_BILLING_FLAG;
export const SPEND_ANALYSIS_FLAG = featureFlagKeys.SPEND_ANALYSIS_FLAG;
export const EXPERIMENT_SUGGESTIONS_FLAG =
  featureFlagKeys.EXPERIMENT_SUGGESTIONS_FLAG;
/** Autoresearch (metric-optimization loop). Staff-gated while it bakes. */
export const AUTORESEARCH_FLAG = featureFlagKeys.AUTORESEARCH_FLAG;
export const DISCOVERY_RUN_FLAG = featureFlagKeys.DISCOVERY_RUN_FLAG;
export const ONBOARDING_TEST_TOOLS_FLAG =
  featureFlagKeys.ONBOARDING_TEST_TOOLS_FLAG;
// Gates the entire canvas feature: the app rail's Channels space, the /website
// routes, channels and dashboards.
export const PROJECT_BLUEBIRD_FLAG = featureFlagKeys.PROJECT_BLUEBIRD_FLAG;
/**
 * Gates the new channels layout (channel-scoped sidebar + task Activity panel).
 * Off keeps the previous experience and its "Enable channels" toggle. Requires
 * project-bluebird. The key predates the rename, matching the live flag.
 */
export const CHANNELS_LAYOUT_FLAG = featureFlagKeys.CHANNELS_LAYOUT_FLAG;
// Gates the Loops feature: the sidebar Loops space and the per-channel Loops tab.
export const LOOPS_FLAG = featureFlagKeys.LOOPS_FLAG;
/** Desktop Loops read and write workflows (`hog_flows`) instead of the loops API. */
export const LOOPS_HOG_FLOWS_FLAG = featureFlagKeys.LOOPS_HOG_FLOWS_FLAG;
export const DESKTOP_HOME_FLAG = featureFlagKeys.DESKTOP_HOME_FLAG;
export const SAVED_SEARCHES_RAIL_FLAG =
  featureFlagKeys.SAVED_SEARCHES_RAIL_FLAG;
export const TASKS_PREWARM_SANDBOX_FLAG =
  featureFlagKeys.TASKS_PREWARM_SANDBOX_FLAG;
export const GLM_MODEL_FLAG = featureFlagKeys.GLM_MODEL_FLAG;
export const GLM53_MODEL_FLAG = featureFlagKeys.GLM53_MODEL_FLAG;
export const GLM53_FLASH_MODEL_FLAG = featureFlagKeys.GLM53_FLASH_MODEL_FLAG;
/** PostHog Desktop: show DeepSeek V4 Flash in the model picker. Off = hidden. */
export const DEEPSEEK_MODEL_FLAG = featureFlagKeys.DEEPSEEK_MODEL_FLAG;

export const TASK_ANALYSIS_FLAG = featureFlagKeys.TASK_ANALYSIS_FLAG;
export const KIMI_MODEL_FLAG = featureFlagKeys.KIMI_MODEL_FLAG;
/** Gates the Fast Mode section of the reasoning dropdown. */
export const FAST_MODE_FLAG = featureFlagKeys.FAST_MODE_FLAG;
/** Spoken narration (agent speaks via the `speak` tool). Gated for a staged rollout. */
export const SPOKEN_NARRATION_FLAG = featureFlagKeys.SPOKEN_NARRATION_FLAG;
export const CODEX_OWN_SUBSCRIPTION_FLAG =
  featureFlagKeys.CODEX_OWN_SUBSCRIPTION_FLAG;
export const CLAUDE_OWN_SUBSCRIPTION_FLAG =
  featureFlagKeys.CLAUDE_OWN_SUBSCRIPTION_FLAG;
// Gates importing and relaying local MCP servers into cloud task runs.
export const LOCAL_MCP_IMPORT_FLAG = featureFlagKeys.LOCAL_MCP_IMPORT_FLAG;
/**
 * Team MCP gateway (shared credentials, per-scope tool policies, agent
 * service accounts, audit log) replacing the per-user MCP marketplace.
 * Owned by the backend rollout in posthog/posthog — same flag key there.
 */
export const MCP_GATEWAY_FLAG = featureFlagKeys.MCP_GATEWAY_FLAG;
/**
 * Shows the task cost as text beside the context ring rather than only inside
 * the popover.
 */
export const TASK_COST_VISIBLE_FLAG = featureFlagKeys.TASK_COST_VISIBLE_FLAG;
/**
 * Remote in-app announcements. The flag's JSON payload carries the
 * announcements (schema: `announcements.ts`); rollout % arms the system.
 * All broad announcements go through this — do not add ad-hoc promo
 * surfaces (see docs/ANNOUNCEMENTS.md).
 */
export const ANNOUNCEMENTS_FLAG = featureFlagKeys.ANNOUNCEMENTS_FLAG;
/** Gates the PR-refund action in the inbox (matches the web SIGNALS_PR_REFUNDS flag). */
export const SIGNALS_PR_REFUNDS_FLAG = featureFlagKeys.SIGNALS_PR_REFUNDS_FLAG;
/**
 * Gates reports living in the channels sidebar: the per-space Reports tab and its
 * report detail route, plus report entries in the feed. Requires project-bluebird.
 */
export const CHANNEL_REPORTS_FLAG = featureFlagKeys.CHANNEL_REPORTS_FLAG;

/**
 * The global reports inbox: one sectioned, keyboard-triageable page for every
 * report, reclaiming the inbox nav slot from the channel-reports takeover.
 * The per-space sidebar list stays the working set beside it.
 */
export const REPORTS_INBOX_FLAG = featureFlagKeys.REPORTS_INBOX_FLAG;

/**
 * One-report-at-a-time keyboard triage inside the reports inbox. On by
 * default in dev builds for iteration (see useTriageFocusEnabled); off in
 * production until it stabilizes.
 */
export const TRIAGE_FOCUS_FLAG = featureFlagKeys.TRIAGE_FOCUS_FLAG;

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
 */
export const BEDROCK_LLM_GATEWAY_FLAG =
  featureFlagKeys.BEDROCK_LLM_GATEWAY_FLAG;

/** Variants of {@link BEDROCK_LLM_GATEWAY_FLAG}. */
export const BEDROCK_GATEWAY_VARIANTS = ["test", "control"] as const;

export type BedrockGatewayVariant = (typeof BEDROCK_GATEWAY_VARIANTS)[number];
/** Gates the organization context wiki: the Context explorer in the nav rails. */
export const CONTEXT_LAYER_FLAG = featureFlagKeys.CONTEXT_LAYER_FLAG;

export const BACKGROUND_AGENT_LOGS_FLAG =
  featureFlagKeys.BACKGROUND_AGENT_LOGS_FLAG;
export const CUSTOM_IMAGES_FEATURE_FLAG =
  featureFlagKeys.CUSTOM_IMAGES_FEATURE_FLAG;
export const PI_HARNESS_FLAG = featureFlagKeys.PI_HARNESS_FLAG;
export const TWIG_CLOUD_MODE_FLAG = featureFlagKeys.TWIG_CLOUD_MODE_FLAG;
export const USER_SPEND_LIMIT_FLAG = featureFlagKeys.USER_SPEND_LIMIT_FLAG;
