import type { SpanContext } from "@opentelemetry/api";
import {
  buildPosthogPropertiesHeaderLines,
  buildPosthogPropertiesHeaderRecord,
  buildPosthogSessionHeaderLines,
  buildPosthogSessionHeaderRecord,
} from "@posthog/agent-contracts/posthog-property-headers";
import type { GatewayEnv } from "../adapters/claude/session/options";
import type { Task } from "../types";
import {
  fallbackGatewayProduct,
  type GatewayProduct,
  type GatewayTarget,
  modelIdForGatewayRoute,
  resolveGatewayTarget,
} from "../utils/gateway";
import type { Logger } from "../utils/logger";
import type { AgentServerConfig } from "./types";

export interface GatewayEnvInput {
  runSpanContext?: SpanContext;
  isInternal?: boolean;
  originProduct?: Task["origin_product"] | null;
  gatewayProduct?: GatewayProduct;
  signalReportId?: string | null;
  aiStage?: string | null;
  aiAgentName?: string | null;
  taskId?: string | null;
  taskRunId?: string | null;
  taskUserId?: number | null;
  taskTitle?: string | null;
  taskOriginKey?: string | null;
  repositories?: string[];
  runtimeAdapter?: string | null;
  sandboxEnvironmentId?: string | null;
  snapshotKind?: string | null;
  prewarmed?: boolean | null;
  executionEnvironment?: "local" | "cloud";
  sharedPromptCache?: boolean;
  runPolicySource?: string;
}

export class AiGatewayNotConfiguredError extends Error {
  constructor(message: string) {
    super(message);
    this.name = "AiGatewayNotConfiguredError";
  }
}

/**
 * The run's scoped gateway token. The worker routes a product and mints its
 * token together, so a run missing either cannot reach a model.
 */
function requireGatewayToken(target: GatewayTarget, logger: Logger): string {
  const token = process.env.AI_GATEWAY_TOKEN?.trim();
  let problem: string | undefined;
  if (!target.routed) {
    problem = `AI_GATEWAY_URL and AI_GATEWAY_PRODUCTS must route ai_product ${target.aiProduct}; got AI_GATEWAY_PRODUCTS=${JSON.stringify(process.env.AI_GATEWAY_PRODUCTS ?? "")}`;
  } else if (!token) {
    problem = `AI_GATEWAY_TOKEN is required for ai_product ${target.aiProduct}`;
  }
  if (problem !== undefined || !token) {
    const message = problem ?? "AI_GATEWAY_TOKEN is required";
    logger.error(message);
    throw new AiGatewayNotConfiguredError(message);
  }
  return token;
}

export function buildGatewayEnv(
  config: Pick<AgentServerConfig, "apiUrl" | "projectId" | "serviceTier">,
  {
    runSpanContext,
    isInternal = false,
    originProduct,
    gatewayProduct,
    signalReportId,
    aiStage,
    aiAgentName,
    taskId,
    taskRunId,
    taskUserId,
    taskTitle,
    taskOriginKey,
    repositories,
    runtimeAdapter,
    sandboxEnvironmentId,
    snapshotKind,
    prewarmed,
    executionEnvironment,
    sharedPromptCache,
    runPolicySource,
  }: GatewayEnvInput = {},
  logger: Logger,
): GatewayEnv {
  const { apiUrl, projectId, serviceTier } = config;
  const target = resolveGatewayTarget({
    product: gatewayProduct ?? fallbackGatewayProduct(isInternal),
    aiStage,
    posthogHost: apiUrl,
  });
  const { baseUrl: gatewayUrl, aiProduct, aiStage: resolvedStage } = target;
  const openaiBaseUrl = `${gatewayUrl}/v1`;
  const llmBearer = requireGatewayToken(target, logger);
  // Task metadata rides the X-PostHog-Properties blob onto $ai_generation.
  // Claude sends it via ANTHROPIC_CUSTOM_HEADERS and Codex via
  // `model_providers.posthog.http_headers`, hence the record form. `ai_product`
  // and `team_id` ride here because Go has no product route or project header.
  const properties = {
    // Gateway headers live for the session, so correlate with its enclosing run.
    task_run_trace_id: runSpanContext?.traceId,
    task_run_span_id: runSpanContext?.spanId,
    task_origin_product: originProduct,
    task_internal: isInternal,
    signal_report_id: signalReportId,
    ai_stage: resolvedStage,
    // The team-scoped agent name; `ai_stage` stays a bounded fleet-wide tag.
    ai_agent_name: aiAgentName,
    task_id: taskId,
    task_run_id: taskRunId,
    task_user_id: taskUserId,
    task_title: taskTitle,
    task_origin_key: taskOriginKey,
    task_repositories: repositories?.length
      ? JSON.stringify(repositories)
      : null,
    task_runtime_adapter: runtimeAdapter,
    task_sandbox_environment_id: sandboxEnvironmentId,
    task_snapshot_kind: snapshotKind,
    task_prewarmed: prewarmed,
    task_execution_environment: executionEnvironment ?? "cloud",
    task_run_policy_source: runPolicySource,
    ai_product: aiProduct,
    team_id: projectId,
  };
  const customHeaders = [
    buildPosthogPropertiesHeaderLines(properties),
    buildPosthogSessionHeaderLines(taskId),
  ]
    .filter(Boolean)
    .join("\n");
  const openaiCustomHeaders: Record<string, string> = {
    ...buildPosthogPropertiesHeaderRecord(properties),
    ...buildPosthogSessionHeaderRecord(taskId),
  };
  // The gateway copies this into the OpenAI body's `service_tier`, the only way
  // a Codex run reaches flex or priority: Codex omits tiers its catalogue lacks.
  if (serviceTier) {
    openaiCustomHeaders["X-PostHog-Service-Tier"] = serviceTier;
    if (serviceTier === "flex") {
      openaiCustomHeaders["X-PostHog-Flex-Fallback"] = "standard";
    }
  }
  // The Go gateway then drops Codex's per-session prompt_cache_key on every
  // request of the process, sub-agents included, so runs share one cache.
  if (sharedPromptCache) {
    openaiCustomHeaders["X-PostHog-Prompt-Cache-Scope"] = "shared";
  }
  // Codex sends no trace header, so the gateway stamps a fresh id per
  // request and a run's generations each land in a trace of one. Codex-only:
  // this header outranks `traceparent`, so setting it for Claude would
  // replace the per-turn ids its CLI mints with one id for the whole run.
  if (taskRunId && runtimeAdapter === "codex") {
    openaiCustomHeaders["X-PostHog-Trace-Id"] = taskRunId;
  }

  return {
    anthropicBaseUrl: gatewayUrl,
    anthropicAuthToken: llmBearer,
    openaiBaseUrl,
    openaiApiKey: llmBearer,
    anthropicCustomHeaders: customHeaders,
    openaiCustomHeaders,
    posthogProjectId: String(projectId),
  };
}

export interface PiProviderRoute {
  apiKey: string;
  baseUrl: string;
  headers: Record<string, string>;
  model: string | undefined;
}

/** The Pi provider's route on Go under the run's scoped token. */
export function buildPiProviderRoute(
  config: Pick<AgentServerConfig, "apiUrl" | "projectId">,
  {
    gatewayProduct,
    aiStage,
    taskId,
    model,
    properties,
  }: {
    gatewayProduct?: GatewayProduct;
    aiStage?: string | null;
    taskId?: string | null;
    model?: string;
    properties: Record<string, string | number | boolean | null | undefined>;
  },
  logger: Logger,
): PiProviderRoute {
  const target = resolveGatewayTarget({
    product: gatewayProduct ?? fallbackGatewayProduct(),
    aiStage,
    posthogHost: config.apiUrl,
  });
  return {
    apiKey: requireGatewayToken(target, logger),
    baseUrl: target.baseUrl,
    // Go reads one properties blob and strips `$` keys, so the session id has its own header.
    headers: {
      ...buildPosthogPropertiesHeaderRecord({
        ...properties,
        ai_product: target.aiProduct,
        team_id: config.projectId,
      }),
      ...buildPosthogSessionHeaderRecord(taskId),
    },
    model: modelIdForGatewayRoute(model),
  };
}

/**
 * The codex session's LLM auth, from the resolved gateway env. Codex must never
 * read the raw run credential: the bearer is the per-run scoped token (see
 * buildGatewayEnv).
 */
export function codexAuthFromGatewayEnv(env: GatewayEnv): {
  apiBaseUrl: string;
  apiKey: string;
} {
  return { apiBaseUrl: env.openaiBaseUrl, apiKey: env.openaiApiKey };
}
