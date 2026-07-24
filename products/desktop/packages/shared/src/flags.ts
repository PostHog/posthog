export const BILLING_FLAG = "posthog-code-billing";
export const SPEND_ANALYSIS_FLAG = "posthog-code-spend-analysis";
/**
 * Launch switch for the one-time usage-based billing announcement: flip at
 * cutover, delete once the fleet has acknowledged.
 */
export const USAGE_BILLING_FLAG = "posthog-code-usage-billing";
export const EXPERIMENT_SUGGESTIONS_FLAG =
  "posthog-code-experiment-suggestions";
export const SYNC_CLOUD_TASKS_FLAG = "posthog-code-sync-cloud-tasks";
/** Autoresearch (metric-optimization loop). Staff-gated while it bakes. */
export const AUTORESEARCH_FLAG = "posthog-code-autoresearch";
export const DISCOVERY_RUN_FLAG = "posthog-code-discovery-run";
// Gates the entire canvas feature: the app rail's Channels space, the /website
// routes, channels and dashboards.
export const PROJECT_BLUEBIRD_FLAG = "project-bluebird";
// Gates the Loops feature: the sidebar Loops space and the per-channel Loops tab.
export const LOOPS_FLAG = "loops";
export const TASKS_PREWARM_SANDBOX_FLAG = "tasks-prewarm-sandbox";
export const GLM_MODEL_FLAG = "posthog-code-glm-model";
/** Spoken narration (agent speaks via the `speak` tool). Gated for a staged rollout. */
export const SPOKEN_NARRATION_FLAG = "posthog-code-spoken-narration";
// Gates importing and relaying local MCP servers into cloud task runs.
export const LOCAL_MCP_IMPORT_FLAG = "posthog-code-local-mcp-import";
/** Per-task estimated cost readout in the context usage indicator. */
export const TASK_COST_FLAG = "posthog-code-task-cost";
