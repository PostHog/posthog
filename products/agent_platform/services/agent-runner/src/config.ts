/**
 * Typed configuration loader for the runner.
 *
 * Extends `PlatformConfigSchema` with the worker-loop knobs (concurrency,
 * model selection, per-provider API keys). Read once at boot in `index.ts`;
 * everything else inside the service receives the typed `Config`.
 */

import { z } from 'zod'

import {
    DEV_ENCRYPTION_KEY,
    DEV_POSTHOG_API_BASE_URL,
    DEV_REDIS_URL,
    extendEnvKeyMap,
    isDev,
    loadConfigFromEnv,
    PLATFORM_ENV_KEY_MAP,
    PlatformConfigSchema,
    requiredInProd,
    requiredInProdUnsetInDev,
    WEB_SEARCH_PROVIDER_NAMES,
} from '@posthog/agent-shared'

// Dev SeaweedFS defaults — the PostHog dev stack pre-creates the `posthog`
// bucket on `seaweedfs:8333` (anonymous mode, so access/secret are `any`). Gated by
// `isDev()` so prod (NODE_ENV=production) must set AGENT_{MEMORY,BUNDLE}_S3_*
// explicitly; without them the bundle-store fail-fast in index.ts trips.
const DEV_S3_ENDPOINT = 'http://localhost:8333'
const DEV_S3_BUCKET = 'posthog'
const DEV_S3_ACCESS_KEY_ID = 'any'
const DEV_S3_SECRET_ACCESS_KEY = 'any'

// Deterministic local ai-gateway phs_ bearer (dev only) — must stay
// byte-identical to bin/setup-gateway-e2e's DEV_GATEWAY_PHS, which publishes the
// matching credential blob to the gateway's local valkey (a mismatch 401s the
// whole e2e silently). Exported so config.test.ts asserts against this const
// instead of re-hardcoding the literal.
export const DEV_GATEWAY_PHS = 'phs_localgatewaye2elocalgatewaye2e0001'

export const AgentRunnerConfigSchema = PlatformConfigSchema.extend({
    // Bus (publishes lifecycle events) + smokescreen (tool/gateway/MCP egress) are
    // required in prod, enforced at config-load rather than via boot guards.
    redisUrl: requiredInProd(DEV_REDIS_URL, 'REDIS_URL', { url: true }).describe(
        'SessionEventBus the runner publishes lifecycle events to. Required in prod; dev defaults to local Redis.'
    ),
    httpsProxy: requiredInProdUnsetInDev('HTTPS_PROXY', { url: true }).describe(
        'Outbound HTTP proxy (smokescreen) for tool / gateway / MCP egress. Required in prod; unset in dev (fetches go direct).'
    ),
    // EncryptedFields (encrypted_env + credential broker) throws on empty keys; tools
    // need the API base. Required in prod, enforced at config-load.
    encryptionSaltKeys: requiredInProd(DEV_ENCRYPTION_KEY, 'ENCRYPTION_SALT_KEYS').describe(
        'Comma-separated UTF-8 Fernet keys (match Django EncryptedTextField). Required in prod; deterministic dev default.'
    ),
    posthogApiBaseUrl: requiredInProd(DEV_POSTHOG_API_BASE_URL, 'POSTHOG_API_BASE_URL', { url: true }).describe(
        'PostHog API base forwarded onto ToolContext for native tools. Required in prod; dev defaults to localhost:8010.'
    ),
    maxConcurrency: z.coerce.number().int().positive().default(8).describe('In-flight sessions per worker process.'),
    healthPort: z.coerce
        .number()
        .int()
        .positive()
        .default(() => (isDev() ? 3032 : 8083))
        .describe(
            'Port for the minimal GET /healthz liveness server. The worker has no request path; this is its only listener. Dev defaults to 3032 (lines up after ingress 3030 / janitor 3031); deployed sets it explicitly in the chart.'
        ),
    maxOutputTokens: z.coerce
        .number()
        .int()
        .positive()
        .optional()
        .describe('Operator override capping per-turn max_tokens below the model ceiling. Unset → model ceiling.'),
    useAiGateway: z
        .union([z.literal('1'), z.literal('0'), z.literal('true'), z.literal('false')])
        .default(() => (isDev() ? '1' : '0'))
        .transform((v) => v === '1' || v === 'true')
        .describe(
            'When truthy (`1`/`true`), routes every model call through PostHog ai-gateway via posthogAiGatewayModel(). Dev defaults on (the local default is the gateway); prod sets it explicitly in the chart. Spec.model still picks the underlying model id.'
        ),
    aiGatewayUrl: z
        .string()
        .url()
        .default(() => (isDev() ? 'http://localhost:8080/v1' : 'http://ai-gateway/v1'))
        .describe(
            'Custom baseUrl for the posthogAiGatewayModel factory. Dev defaults to the local sibling gateway on :8080; prod points at the in-cluster service.'
        ),
    posthogAiGatewayKey: z
        .string()
        .optional()
        .transform((v): string | undefined => v ?? (isDev() ? DEV_GATEWAY_PHS : undefined))
        .describe(
            'Static ai-gateway bearer — a `phs_` project secret key with the `llm_gateway:read` scope. On the gateway path it authenticates every model + usage call (required there); on the direct path it falls through as the first-priority provider apiKey. Dev defaults to the deterministic local phs_ that bin/setup-gateway-e2e provisions.'
        ),
    anthropicApiKey: z.string().optional().describe('Anthropic API key. Second-priority for pi-ai default apiKey.'),
    openaiApiKey: z.string().optional().describe('OpenAI API key. Third-priority for pi-ai default apiKey.'),
    modelApiKey: z.string().optional().describe('Catch-all model API key. Last-priority for pi-ai default apiKey.'),
    posthogAnalyticsApiKey: z
        .string()
        .optional()
        .transform((v): string | undefined => v ?? (isDev() ? 'phc_localposthogprojecttoken' : undefined))
        .describe(
            'Fallback PostHog project key for the LLM analytics sink. By default each event routes to the owning team’s OWN project (team_id → phc_); this key only catches events whose team has no api_token. Setting either this or POSTHOG_ANALYTICS_HOST enables the sink; with neither → NoopAnalyticsSink (CI). Dev defaults to the local project token.'
        ),
    posthogAnalyticsHost: z
        .string()
        .url()
        .optional()
        .transform((v): string | undefined => v ?? (isDev() ? 'http://localhost:8010' : undefined))
        .describe(
            'PostHog capture host for the analytics sink (the region the runner’s teams live in). Defaults to `https://us.posthog.com` when unset in prod, and to local Django (`http://localhost:8010`) in dev. Setting it enables per-team routing even without a fallback key.'
        ),
    approvalLinkScheme: z
        .string()
        .default(isDev() ? 'posthog-code-dev' : 'posthog-code')
        .describe(
            'Custom-protocol scheme that PostHog Code registers for deep links (the agent console now lives in the PostHog Code app). Used to build clickable approval links (`<scheme>://approval/<id>`) surfaced to the model on a gated tool call so non-PostHog-Code clients (Slack, MCP) can open the approval in the desktop app. Dev → `posthog-code-dev`, prod → `posthog-code`.'
        ),
    memoryS3Endpoint: requiredInProd(DEV_S3_ENDPOINT, 'AGENT_MEMORY_S3_ENDPOINT', { url: true }).describe(
        'S3-compatible endpoint for agent-memory file storage. Required everywhere — runner refuses to start without it (fail closed at config-load in prod). Dev defaults to local SeaweedFS.'
    ),
    memoryS3Region: z
        .string()
        .default('us-east-1')
        .describe('Region for the memory bucket. SeaweedFS ignores; real S3 honours.'),
    memoryS3Bucket: requiredInProd(DEV_S3_BUCKET, 'AGENT_MEMORY_S3_BUCKET').describe(
        'Bucket holding agent memory files. Dev defaults to the SeaweedFS `posthog` bucket; required in prod.'
    ),
    memoryS3Prefix: z
        .string()
        .default('agent_memory')
        .describe('Per-deployment key prefix inside the bucket. Default `agent_memory`.'),
    memoryS3AccessKeyId: z
        .string()
        .optional()
        .transform((v): string | undefined => v ?? (isDev() ? DEV_S3_ACCESS_KEY_ID : undefined))
        .describe(
            'Optional explicit S3 access key id; falls back to SDK default chain. Dev defaults to SeaweedFS anonymous (`any`/`any`).'
        ),
    memoryS3SecretAccessKey: z
        .string()
        .optional()
        .transform((v): string | undefined => v ?? (isDev() ? DEV_S3_SECRET_ACCESS_KEY : undefined))
        .describe('Optional explicit S3 secret access key. Dev defaults to SeaweedFS anonymous (`any`/`any`).'),
    memoryS3ForcePathStyle: z
        .union([z.literal('1'), z.literal('0'), z.literal('true'), z.literal('false')])
        .default('1')
        .transform((v) => v === '1' || v === 'true')
        .describe(
            'forcePathStyle for the S3 client. Default true (SeaweedFS + MinIO both need it; real S3 accepts it).'
        ),
    bundleS3Endpoint: z
        .string()
        .url()
        .optional()
        .transform((v): string | undefined => v ?? (isDev() ? DEV_S3_ENDPOINT : undefined))
        .describe(
            'S3-compatible endpoint for agent-bundle storage. Dev defaults to local SeaweedFS; prod unset means SDK regional default.'
        ),
    bundleS3Region: z
        .string()
        .default('us-east-1')
        .describe('Region for the bundle bucket. SeaweedFS ignores; real S3 honours.'),
    bundleS3Bucket: requiredInProd(DEV_S3_BUCKET, 'AGENT_BUNDLE_S3_BUCKET').describe(
        'Bucket holding agent bundles (per-revision compiled code + spec + skills). Dev defaults to the SeaweedFS `posthog` bucket; required in prod — the runner fails closed at config-load without it.'
    ),
    bundleS3Prefix: z
        .string()
        .default('agent_bundles')
        .describe('Per-deployment key prefix inside the bucket. Default `agent_bundles`.'),
    bundleS3AccessKeyId: z
        .string()
        .optional()
        .transform((v): string | undefined => v ?? (isDev() ? DEV_S3_ACCESS_KEY_ID : undefined))
        .describe(
            'Optional explicit S3 access key id; falls back to SDK default chain. Dev defaults to SeaweedFS anonymous (`any`/`any`).'
        ),
    bundleS3SecretAccessKey: z
        .string()
        .optional()
        .transform((v): string | undefined => v ?? (isDev() ? DEV_S3_SECRET_ACCESS_KEY : undefined))
        .describe('Optional explicit S3 secret access key. Dev defaults to SeaweedFS anonymous (`any`/`any`).'),
    bundleS3ForcePathStyle: z
        .union([z.literal('1'), z.literal('0'), z.literal('true'), z.literal('false')])
        .default('1')
        .transform((v) => v === '1' || v === 'true')
        .describe(
            'forcePathStyle for the S3 client. Default true (SeaweedFS + MinIO both need it; real S3 accepts it).'
        ),
    devMcpBearerToken: z
        .string()
        .optional()
        .describe(
            "Dev-only bearer attached to MCP requests when the ref has no `auth.provider` configured. Lets a local bundle (concierge) reach the dev MCP server with the operator's PAT, before per-session credential plumbing exists for external MCPs. **Refused at boot when NODE_ENV=production** — prod must route auth via `auth.provider` or a bring-your-own-token secret."
        ),
    sandboxBackend: z
        .enum(['docker', 'modal'])
        .optional()
        .transform((v): 'docker' | 'modal' | undefined => v ?? (isDev() ? 'docker' : undefined))
        .describe(
            "Sandbox pool impl. `modal` (prod) provisions per-session Modal sandboxes; `docker` (local dev) runs the posthog-agent-sandbox-host image via the docker socket. Defaults to `docker` under `isDev()` so `bin/start` works without configuration; prod must set this explicitly or `selectSandboxPool` throws at boot. In-process sandbox is selected by tests directly, never via config — it has no isolation and isn't a valid prod / local-dev choice."
        ),
    sandboxHostImage: z
        .string()
        .optional()
        .transform((v): string | undefined => v ?? (isDev() ? 'posthog/agent-sandbox-host:dev' : undefined))
        .describe(
            'Canonical `posthog-agent-sandbox-host` image reference (pinned by SHA in prod). Applies to both backends unless an `AGENT_SANDBOX_{DOCKER,MODAL}_IMAGE` override is set. Defaults to the locally-built `posthog/agent-sandbox-host:dev` tag under `isDev()` (matches `services/agent-sandbox-host/README.md` build instructions) so `bin/start` works without configuration; prod must set this explicitly.'
        ),
    sandboxDockerImage: z
        .string()
        .optional()
        .describe(
            'Backend-specific Docker image override. Takes precedence over `sandboxHostImage` for the docker backend.'
        ),
    sandboxModalImage: z
        .string()
        .optional()
        .describe(
            'Backend-specific Modal image override. Takes precedence over `sandboxHostImage` for the modal backend.'
        ),
    modalAppName: z.string().optional().describe('Optional Modal app name. When unset the Modal SDK uses its default.'),
    modalRegion: z
        .string()
        .optional()
        .describe(
            'Modal region pin (e.g. `us-east`, `eu-west`). Defaults to whatever `resolveRegion()` derives from `CLOUD_DEPLOYMENT` inside the Modal pool when unset.'
        ),
    sandboxOutboundCidrAllowlist: z
        .string()
        .optional()
        .transform((v): string[] =>
            v
                ? v
                      .split(',')
                      .map((s) => s.trim())
                      .filter(Boolean)
                : []
        )
        .describe(
            'Comma-separated CIDRs the Modal custom-tool sandbox may reach outbound. Empty (default) → the sandbox has NO outbound internet (Modal `block_network`). Custom tools compute and return; the runner makes any egress through smokescreen. Set only if a custom tool genuinely needs direct egress to a known range.'
        ),
    linkRedirectBaseUrl: z
        .string()
        .url()
        .default(() => (isDev() ? 'http://localhost:3030' : 'https://agents.posthog.com'))
        .describe(
            'Public base URL of the ingress, used to build OAuth callback redirect URIs for identity linking (`<base>/link/<provider>/callback`). Dev defaults to the local ingress; prod sets the deployed ingress URL.'
        ),
    webSearchProvider: z
        .enum(WEB_SEARCH_PROVIDER_NAMES)
        .optional()
        .describe(
            'Primary `@posthog/web-search` provider id (`exa` | `tavily` | `brave`), tried first. A typo fails fast at config load rather than silently disabling the tool. Unset → the highest-priority keyed provider acts as primary. With no provider key set at all the tool is gated out of every session.'
        ),
    webSearchFallbacks: z
        .string()
        .optional()
        .refine(
            (v) => {
                if (!v) {
                    return true
                }
                const tokens = v
                    .split(',')
                    .map((s) => s.trim().toLowerCase())
                    .filter(Boolean)
                return tokens.every((t) => (WEB_SEARCH_PROVIDER_NAMES as readonly string[]).includes(t))
            },
            {
                message: `webSearchFallbacks must be a comma-separated list of: ${WEB_SEARCH_PROVIDER_NAMES.join(', ')}`,
            }
        )
        .describe(
            'Comma-separated ordered fallback provider ids tried after the primary on error. A typo fails fast at config load (matches the primary). Empty → every other keyed provider is a last-resort fallback in natural order (exa, tavily, brave).'
        ),
    exaApiKey: z.string().optional().describe('Exa search API key. Enables the `exa` web-search provider.'),
    tavilyApiKey: z.string().optional().describe('Tavily search API key. Enables the `tavily` web-search provider.'),
    braveApiKey: z
        .string()
        .optional()
        .describe('Brave Search API subscription token. Enables the `brave` web-search provider.'),
})

export type AgentRunnerConfig = z.infer<typeof AgentRunnerConfigSchema>

const ENV_KEY_MAP = extendEnvKeyMap<AgentRunnerConfig>(PLATFORM_ENV_KEY_MAP, {
    AGENT_MAX_CONCURRENCY: 'maxConcurrency',
    AGENT_RUNNER_HEALTH_PORT: 'healthPort',
    AGENT_MAX_OUTPUT_TOKENS: 'maxOutputTokens',
    AGENT_USE_AI_GATEWAY: 'useAiGateway',
    POSTHOG_AI_GATEWAY_URL: 'aiGatewayUrl',
    POSTHOG_AI_GATEWAY_KEY: 'posthogAiGatewayKey',
    ANTHROPIC_API_KEY: 'anthropicApiKey',
    OPENAI_API_KEY: 'openaiApiKey',
    MODEL_API_KEY: 'modelApiKey',
    POSTHOG_ANALYTICS_API_KEY: 'posthogAnalyticsApiKey',
    POSTHOG_ANALYTICS_HOST: 'posthogAnalyticsHost',
    AGENT_APPROVAL_LINK_SCHEME: 'approvalLinkScheme',
    AGENT_MEMORY_S3_ENDPOINT: 'memoryS3Endpoint',
    AGENT_MEMORY_S3_REGION: 'memoryS3Region',
    AGENT_MEMORY_S3_BUCKET: 'memoryS3Bucket',
    AGENT_MEMORY_S3_PREFIX: 'memoryS3Prefix',
    AGENT_MEMORY_S3_ACCESS_KEY_ID: 'memoryS3AccessKeyId',
    AGENT_MEMORY_S3_SECRET_ACCESS_KEY: 'memoryS3SecretAccessKey',
    AGENT_MEMORY_S3_FORCE_PATH_STYLE: 'memoryS3ForcePathStyle',
    AGENT_BUNDLE_S3_ENDPOINT: 'bundleS3Endpoint',
    AGENT_BUNDLE_S3_REGION: 'bundleS3Region',
    AGENT_BUNDLE_S3_BUCKET: 'bundleS3Bucket',
    AGENT_BUNDLE_S3_PREFIX: 'bundleS3Prefix',
    AGENT_BUNDLE_S3_ACCESS_KEY_ID: 'bundleS3AccessKeyId',
    AGENT_BUNDLE_S3_SECRET_ACCESS_KEY: 'bundleS3SecretAccessKey',
    AGENT_BUNDLE_S3_FORCE_PATH_STYLE: 'bundleS3ForcePathStyle',
    AGENT_DEV_MCP_BEARER_TOKEN: 'devMcpBearerToken',
    SANDBOX_BACKEND: 'sandboxBackend',
    SANDBOX_HOST_IMAGE: 'sandboxHostImage',
    SANDBOX_DOCKER_IMAGE: 'sandboxDockerImage',
    SANDBOX_MODAL_IMAGE: 'sandboxModalImage',
    SANDBOX_OUTBOUND_CIDR_ALLOWLIST: 'sandboxOutboundCidrAllowlist',
    MODAL_APP_NAME: 'modalAppName',
    MODAL_REGION: 'modalRegion',
    AGENT_INGRESS_PUBLIC_URL: 'linkRedirectBaseUrl',
    AGENT_WEB_SEARCH_PROVIDER: 'webSearchProvider',
    AGENT_WEB_SEARCH_FALLBACKS: 'webSearchFallbacks',
    EXA_API_KEY: 'exaApiKey',
    TAVILY_API_KEY: 'tavilyApiKey',
    BRAVE_API_KEY: 'braveApiKey',
})

export function loadAgentRunnerConfig(env: NodeJS.ProcessEnv = process.env): AgentRunnerConfig {
    return loadConfigFromEnv(AgentRunnerConfigSchema, ENV_KEY_MAP, env)
}

/**
 * First non-empty *provider* API key for the direct (non-gateway) path:
 * anthropic → openai → catch-all. The gateway bearer (`posthogAiGatewayKey`,
 * a `phs_`) is deliberately excluded — it authenticates the gateway, not a
 * provider, and the gateway path uses it directly via resolveApiKey. (It also
 * dev-defaults now, so including it would shadow real provider keys locally.)
 */
export function defaultApiKeyFromConfig(cfg: AgentRunnerConfig): string | undefined {
    return cfg.anthropicApiKey ?? cfg.openaiApiKey ?? cfg.modelApiKey
}
