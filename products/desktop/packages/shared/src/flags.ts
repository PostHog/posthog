export const BILLING_FLAG = "posthog-code-billing";
export const CLOUD_COMPUTE_BILLING_FLAG =
  "posthog-desktop-cloud-compute-billing";
export const SPEND_ANALYSIS_FLAG = "posthog-code-spend-analysis";
export const EXPERIMENT_SUGGESTIONS_FLAG =
  "posthog-code-experiment-suggestions";
/** Autoresearch (metric-optimization loop). Staff-gated while it bakes. */
export const AUTORESEARCH_FLAG = "posthog-code-autoresearch";
export const DISCOVERY_RUN_FLAG = "posthog-code-discovery-run";
export const ONBOARDING_TEST_TOOLS_FLAG =
  "posthog-desktop-onboarding-test-tools";
// Gates the entire canvas feature: the app rail's Channels space, the /website
// routes, channels and dashboards.
export const PROJECT_BLUEBIRD_FLAG = "project-bluebird";
/**
 * Gates the new channels layout (channel-scoped sidebar + task Activity panel).
 * Off keeps the previous experience and its "Enable channels" toggle. Requires
 * project-bluebird. The key predates the rename, matching the live flag.
 */
export const CHANNELS_LAYOUT_FLAG = "code-spaces-layout";
// Gates the Loops feature: the sidebar Loops space and the per-channel Loops tab.
export const LOOPS_FLAG = "loops";
export const DESKTOP_HOME_FLAG = "desktop-home-flag";
export const TASKS_PREWARM_SANDBOX_FLAG = "tasks-prewarm-sandbox";
export const GLM_MODEL_FLAG = "posthog-code-glm-model";
export const GLM53_MODEL_FLAG = "posthog-code-glm-53-model";
export const GLM53_FLASH_MODEL_FLAG = "posthog-code-glm-53-flash-model";
/** PostHog Desktop: show DeepSeek V4 Flash in the model picker. Off = hidden. */
export const DEEPSEEK_MODEL_FLAG = "posthog-code-deepseek-model";

export const TASK_ANALYSIS_FLAG = "posthog-code-task-analysis";
export const KIMI_MODEL_FLAG = "tasks-kimi-k3";
/** Gates the Fast Mode section of the reasoning dropdown. */
export const FAST_MODE_FLAG = "posthog-desktop-fast-mode";
/** Spoken narration (agent speaks via the `speak` tool). Gated for a staged rollout. */
export const SPOKEN_NARRATION_FLAG = "posthog-code-spoken-narration";
export const CODEX_OWN_SUBSCRIPTION_FLAG =
  "posthog-code-codex-own-subscription";
// Gates importing and relaying local MCP servers into cloud task runs.
export const LOCAL_MCP_IMPORT_FLAG = "posthog-code-local-mcp-import";
/**
 * Team MCP gateway (shared credentials, per-scope tool policies, agent
 * service accounts, audit log) replacing the per-user MCP marketplace.
 * Owned by the backend rollout in posthog/posthog — same flag key there.
 */
export const MCP_GATEWAY_FLAG = "mcp-gateway";
/** Per-task estimated cost readout in the context usage indicator. */
export const TASK_COST_FLAG = "posthog-code-task-cost";
/**
 * Shows the task cost as text beside the context ring rather than only inside
 * the popover. Requires TASK_COST_FLAG, which is what fetches the figure.
 */
export const TASK_COST_VISIBLE_FLAG = "posthog-code-task-cost-visible";
/**
 * Remote in-app announcements. The flag's JSON payload carries the
 * announcements (schema: `announcements.ts`); rollout % arms the system.
 * All broad announcements go through this — do not add ad-hoc promo
 * surfaces (see docs/ANNOUNCEMENTS.md).
 */
export const ANNOUNCEMENTS_FLAG = "posthog-desktop-announcements";
/** Gates the PR-refund action in the inbox (matches the web SIGNALS_PR_REFUNDS flag). */
export const SIGNALS_PR_REFUNDS_FLAG = "signals-pr-refunds";
/**
 * Gates reports living in the channels sidebar: the per-space Reports tab and its
 * report detail route, plus report entries in the feed. Requires project-bluebird.
 */
export const CHANNEL_REPORTS_FLAG = "posthog-desktop-channel-reports";

/**
 * The global reports inbox: one sectioned, keyboard-triageable page for every
 * report, reclaiming the inbox nav slot from the channel-reports takeover.
 * The per-space sidebar list stays the working set beside it.
 */
export const REPORTS_INBOX_FLAG = "posthog-desktop-reports-inbox";

/**
 * One-report-at-a-time keyboard triage inside the reports inbox. On by
 * default in dev builds for iteration (see useTriageFocusEnabled); off in
 * production until it stabilizes.
 */
export const TRIAGE_FOCUS_FLAG = "posthog-desktop-triage-focus";

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
export const BEDROCK_LLM_GATEWAY_FLAG = "bedrock-llm-gateway";

/** Variants of {@link BEDROCK_LLM_GATEWAY_FLAG}. */
export const BEDROCK_GATEWAY_VARIANTS = ["test", "control"] as const;

export type BedrockGatewayVariant = (typeof BEDROCK_GATEWAY_VARIANTS)[number];
/** Gates the organization context wiki: the Context explorer in the nav rails. */
export const CONTEXT_LAYER_FLAG = "context-layer";
