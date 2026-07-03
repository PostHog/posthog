/**
 * Typed configuration loader for the janitor.
 *
 * Extends `PlatformConfigSchema` from `@posthog/agent-shared/config/platform`
 * with the janitor-specific knobs (port, sweep thresholds, internal secret).
 * Every other `process.env.*` access in this package is blocked by the
 * `agent-janitor-no-process-env` semgrep rule — env reads go through
 * `loadAgentJanitorConfig()` only.
 */

import { z } from 'zod'

import {
    DEV_INTERNAL_SIGNING_KEY,
    extendEnvKeyMap,
    isDev,
    loadConfigFromEnv,
    PLATFORM_ENV_KEY_MAP,
    PlatformConfigSchema,
    requiredInProd,
} from '@posthog/agent-shared'

const ONE_MINUTE_MS = 60_000

// Dev SeaweedFS defaults — the PostHog dev stack pre-creates the `posthog`
// bucket on `seaweedfs:8333` (anonymous mode, so access/secret are `any`). Gated by
// `isDev()` so prod (NODE_ENV=production) must set AGENT_{MEMORY,BUNDLE}_S3_*
// explicitly; without them the bundle-store fail-fast in index.ts trips.
const DEV_S3_ENDPOINT = 'http://localhost:8333'
const DEV_S3_BUCKET = 'posthog'
const DEV_S3_ACCESS_KEY_ID = 'any'
const DEV_S3_SECRET_ACCESS_KEY = 'any'

export const AgentJanitorConfigSchema = PlatformConfigSchema.extend({
    port: z.coerce
        .number()
        .int()
        .positive()
        .default(() => (isDev() ? 3031 : 8082))
        .describe('HTTP listen port. Dev defaults to 3031; deployed sets it explicitly.'),
    internalSigningKey: requiredInProd(DEV_INTERNAL_SIGNING_KEY, 'AGENT_INTERNAL_SIGNING_KEY').describe(
        "Shared HMAC signing key (must match Django's `AGENT_INTERNAL_SIGNING_KEY`). Verifies the audience-bound JWT Django sends as `x-internal-secret` (aud = `agent-janitor.rpc`). Gates every endpoint other than `/healthz` — required in prod, dev default for local running."
    ),
    stuckRunningMs: z.coerce
        .number()
        .int()
        .positive()
        .default(5 * ONE_MINUTE_MS)
        .describe('Sweep re-queues `running` sessions older than this many ms.'),
    stuckWaitingMs: z.coerce
        .number()
        .int()
        .positive()
        .default(24 * 60 * ONE_MINUTE_MS)
        .describe('Sweep fails `waiting` sessions older than this many ms.'),
    idleCompletedMs: z.coerce
        .number()
        .int()
        .positive()
        .default(24 * 60 * ONE_MINUTE_MS)
        .describe(
            'Platform-wide floor for the `completed → closed` sweep. ' +
                'Agents that opt into `spec.resume.enabled` may extend this via `max_completed_age_ms`.'
        ),
    maxRetries: z.coerce.number().int().nonnegative().default(3).describe('Poison-pill threshold for re-queues.'),
    idempotencyKeyTtlMs: z.coerce
        .number()
        .int()
        .nonnegative()
        .default(30 * 24 * 60 * ONE_MINUTE_MS)
        .describe(
            'Sweep nulls out `idempotency_key` on sessions older than this so the partial unique index ' +
                'stays compact. By default 30d — by then any redelivery / cron-replay that would have ' +
                'collided already has. Set to 0 to disable.'
        ),
    sweepIntervalMs: z.coerce
        .number()
        .int()
        .positive()
        .default(30 * 1000)
        .describe('How often the in-process sweep timer fires.'),
    sandboxStaleMs: z.coerce
        .number()
        .int()
        .positive()
        .default(10 * ONE_MINUTE_MS)
        .describe(
            'Age past which a `provisioning`/`ready` `agent_sandbox_instance` row is considered ' +
                'orphaned; the sweep terminates the underlying compute (Modal sandbox, etc.) via the ' +
                'provider SDK and marks the row terminated. Default 10 minutes = 2x stuck-running ' +
                'threshold, so a healthy session re-queue + resume cycle doesnt race the reaper.'
        ),
    memoryS3Endpoint: requiredInProd(DEV_S3_ENDPOINT, 'AGENT_MEMORY_S3_ENDPOINT', { url: true }).describe(
        'S3-compatible endpoint for memory file storage. Dev defaults to local SeaweedFS; required in prod — the janitor refuses to start without memory storage.'
    ),
    memoryS3Region: z.string().default('us-east-1').describe('Region for the memory bucket.'),
    memoryS3Bucket: requiredInProd(DEV_S3_BUCKET, 'AGENT_MEMORY_S3_BUCKET').describe(
        'Bucket holding agent memory files. Dev defaults to the SeaweedFS `posthog` bucket; required in prod.'
    ),
    memoryS3Prefix: z.string().default('agent_memory').describe('Per-deployment key prefix inside the bucket.'),
    memoryS3AccessKeyId: z
        .string()
        .optional()
        .transform((v): string | undefined => v ?? (isDev() ? DEV_S3_ACCESS_KEY_ID : undefined))
        .describe(
            'Optional explicit access key id; falls back to SDK default chain. Dev defaults to SeaweedFS anonymous (`any`/`any`).'
        ),
    memoryS3SecretAccessKey: z
        .string()
        .optional()
        .transform((v): string | undefined => v ?? (isDev() ? DEV_S3_SECRET_ACCESS_KEY : undefined))
        .describe('Optional explicit secret access key. Dev defaults to SeaweedFS anonymous (`any`/`any`).'),
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
    bundleS3Region: z.string().default('us-east-1').describe('Region for the bundle bucket.'),
    bundleS3Bucket: requiredInProd(DEV_S3_BUCKET, 'AGENT_BUNDLE_S3_BUCKET').describe(
        'Bucket holding agent bundles (per-revision compiled code + spec + skills). Dev defaults to the SeaweedFS `posthog` bucket; required in prod — the janitor fails closed at boot without it.'
    ),
    bundleS3Prefix: z.string().default('agent_bundles').describe('Per-deployment key prefix inside the bucket.'),
    bundleS3AccessKeyId: z
        .string()
        .optional()
        .transform((v): string | undefined => v ?? (isDev() ? DEV_S3_ACCESS_KEY_ID : undefined))
        .describe(
            'Optional explicit access key id; falls back to SDK default chain. Dev defaults to SeaweedFS anonymous (`any`/`any`).'
        ),
    bundleS3SecretAccessKey: z
        .string()
        .optional()
        .transform((v): string | undefined => v ?? (isDev() ? DEV_S3_SECRET_ACCESS_KEY : undefined))
        .describe('Optional explicit secret access key. Dev defaults to SeaweedFS anonymous (`any`/`any`).'),
    bundleS3ForcePathStyle: z
        .union([z.literal('1'), z.literal('0'), z.literal('true'), z.literal('false')])
        .default('1')
        .transform((v) => v === '1' || v === 'true')
        .describe(
            'forcePathStyle for the S3 client. Default true (SeaweedFS + MinIO both need it; real S3 accepts it).'
        ),
    aiGatewayUrl: z
        .string()
        .url()
        .default(() => (isDev() ? 'http://localhost:8080/v1' : 'http://ai-gateway/v1'))
        .describe(
            'AI gateway base URL (incl. /v1) — the SAME gateway the runner dispatches against. The model-catalog read for models validation hits {url}/models.'
        ),
    posthogAiGatewayKey: z
        .string()
        .optional()
        .describe('Optional phs_ bearer for the model-catalog read; /models is otherwise unauthenticated.'),
})

export type AgentJanitorConfig = z.infer<typeof AgentJanitorConfigSchema>

const ENV_KEY_MAP = extendEnvKeyMap<AgentJanitorConfig>(PLATFORM_ENV_KEY_MAP, {
    PORT: 'port',
    AGENT_INTERNAL_SIGNING_KEY: 'internalSigningKey',
    STUCK_RUNNING_MS: 'stuckRunningMs',
    STUCK_WAITING_MS: 'stuckWaitingMs',
    IDLE_COMPLETED_MS: 'idleCompletedMs',
    MAX_RETRIES: 'maxRetries',
    IDEMPOTENCY_KEY_TTL_MS: 'idempotencyKeyTtlMs',
    SWEEP_INTERVAL_MS: 'sweepIntervalMs',
    SANDBOX_STALE_MS: 'sandboxStaleMs',
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
    POSTHOG_AI_GATEWAY_URL: 'aiGatewayUrl',
    POSTHOG_AI_GATEWAY_KEY: 'posthogAiGatewayKey',
})

export function loadAgentJanitorConfig(env: NodeJS.ProcessEnv = process.env): AgentJanitorConfig {
    return loadConfigFromEnv(AgentJanitorConfigSchema, ENV_KEY_MAP, env)
}
