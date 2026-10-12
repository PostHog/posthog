import type { SpanContext } from "@opentelemetry/api";
import {
  buildPosthogPropertiesHeaderLines,
  buildPosthogPropertiesHeaderRecord,
  buildPosthogScopedPropertyHeaderLines,
  buildPosthogScopedPropertyHeaderRecord,
} from "@posthog/agent-contracts/posthog-property-headers";
import type { GatewayEnv } from "../adapters/claude/session/options";
import type { Task } from "../types";
import { resolveGatewayProduct, resolveGatewayTarget } from "../utils/gateway";
import type { Logger } from "../utils/logger";
import type { AgentServerConfig } from "./types";

export interface GatewayEnvInput {
  runSpanContext?: SpanContext;
  isInternal?: boolean;
  originProduct?: Task["origin_product"] | null;
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
}

export function buildGatewayEnv(
  config: Pick<
    AgentServerConfig,
    "apiKey" | "apiUrl" | "projectId" | "serviceTier"
  >,
  {
    runSpanContext,
    isInternal = false,
    originProduct,
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
  }: GatewayEnvInput = {},
  logger: Logger,
): GatewayEnv {
  const { apiKey, apiUrl, projectId, serviceTier } = config;
  const product = resolveGatewayProduct({ isInternal, originProduct });
  // Go-gateway runs authenticate with the per-run scoped token minted by the
  // worker (pinned product + on-behalf-of team, per-run spend cap), not the
  // run's per-team OAuth token, whose team has no gateway wallet. A routed
  // product with no token therefore stays on the Python gateway. The worker's env values
  // win, because the token is pinned to the product they name.
  const gatewayToken = process.env.AI_GATEWAY_TOKEN?.trim() || undefined;
  let target = resolveGatewayTarget({
    product,
    aiStage,
    posthogHost: apiUrl,
  });
  if (target.isAiGateway && !gatewayToken) {
    logger.warn(
      `AI_GATEWAY_TOKEN missing for routed product ${target.aiProduct}; falling back to the Python gateway`,
    );
    target = resolveGatewayTarget({
      product,
      aiStage,
      posthogHost: apiUrl,
      env: { ...process.env, AI_GATEWAY_URL: undefined },
    });
  }
  const {
    baseUrl: gatewayUrl,
    isAiGateway,
    aiProduct,
    aiStage: resolvedStage,
  } = target;
  const llmBearer = isAiGateway && gatewayToken ? gatewayToken : apiKey;
  const openaiBaseUrl = gatewayUrl.endsWith("/v1")
    ? gatewayUrl
    : `${gatewayUrl}/v1`;
  // Forward task metadata as `x-posthog-property-*` headers so the gateway
  // lifts them onto the $ai_generation event. The Claude path routes these
  // through the Anthropic SDK's ANTHROPIC_CUSTOM_HEADERS env var; the codex
  // path sets them as `model_providers.posthog.http_headers` instead, so we
  // also expose the record form below.
  const gatewayProperties = {
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
  };
  // The Claude path appends the project scope in buildEnvironment from
  // POSTHOG_PROJECT_ID; the codex path has no such hook, so its record below
  // carries the same scope.
  let customHeaders: string;
  let openaiCustomHeaders: Record<string, string>;
  if (isAiGateway) {
    // The Go gateway reads one X-PostHog-Properties JSON blob and ignores
    // per-property headers, and it has no product route, so `ai_product`
    // has to travel in the blob or the spend lands unattributed. `team_id`
    // is included for both adapters because the Go gateway does not read
    // the Python gateway's project-scope header.
    const properties = {
      ...gatewayProperties,
      ai_product: aiProduct,
      team_id: projectId,
    };
    customHeaders = buildPosthogPropertiesHeaderLines(properties);
    openaiCustomHeaders = buildPosthogPropertiesHeaderRecord(properties);
    // The Go gateway writes this into the OpenAI body's `service_tier`, which
    // is the only way a Codex run reaches the flex or priority queue: Codex
    // itself omits a tier its model catalogue does not advertise. Codex-only,
    // so it rides the OpenAI record; the Claude path has no tier concept.
    if (serviceTier) {
      openaiCustomHeaders["X-PostHog-Service-Tier"] = serviceTier;
      if (serviceTier === "flex") {
        openaiCustomHeaders["X-PostHog-Flex-Fallback"] = "standard";
      }
    }
    // Codex sends no trace header, so the gateway stamps a fresh id per
    // request and a run's generations each land in a trace of one. Codex-only:
    // this header outranks `traceparent`, so setting it for Claude would
    // replace the per-turn ids its CLI mints with one id for the whole run.
    if (taskRunId && runtimeAdapter === "codex") {
      openaiCustomHeaders["X-PostHog-Trace-Id"] = taskRunId;
    }
  } else {
    customHeaders = buildPosthogScopedPropertyHeaderLines(
      gatewayProperties,
      projectId,
    );
    // No $ai_session_id on the Go-gateway path above: it strips $-prefixed
    // blob keys, so the session id would be silently dropped there.
    openaiCustomHeaders = buildPosthogScopedPropertyHeaderRecord(
      {
        ...gatewayProperties,
        team_id: projectId,
        $ai_session_id: taskId,
      },
      projectId,
    );
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

/**
 * The codex session's LLM auth, from the resolved gateway env. Codex must never
 * read the raw run credential: on the Go-gateway path the bearer is the per-run
 * scoped token (see buildGatewayEnv).
 */
export function codexAuthFromGatewayEnv(env: GatewayEnv): {
  apiBaseUrl: string;
  apiKey: string;
} {
  return { apiBaseUrl: env.openaiBaseUrl, apiKey: env.openaiApiKey };
}
