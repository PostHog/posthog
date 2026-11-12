import { S3Client, S3ClientConfig } from '@aws-sdk/client-s3'
import { ClickHouseClient, createClient as createClickHouseClient } from '@clickhouse/client'
import https from 'https'
import express from 'ultimate-express'

import { IngestionOutputs } from '~/common/outputs/ingestion-outputs'
import { createRedisV2PoolFromConfig } from '~/common/redis/redis-v2'
import { KeyedRateLimiterService } from '~/common/services/keyed-rate-limiter.service'
import { PostgresRouter } from '~/common/utils/db/postgres'
import { createRedisPoolFromConfig } from '~/common/utils/db/redis'
import { logger, serializeError } from '~/common/utils/logger'
import { captureException } from '~/common/utils/posthog'
import { getBlockDecryptor, getBlockEncryptor } from '~/ingestion/pipelines/sessionreplay/shared/crypto'
import { SessionFeatureStore } from '~/ingestion/pipelines/sessionreplay/shared/features/session-feature-store'
import { getKeyStore } from '~/ingestion/pipelines/sessionreplay/shared/keystore'
import { RedisCachedKeyStore } from '~/ingestion/pipelines/sessionreplay/shared/keystore/cache'
import { SessionMetadataStore } from '~/ingestion/pipelines/sessionreplay/shared/metadata/session-metadata-store'
import { ReplayEventsOutput, SessionFeaturesOutput } from '~/ingestion/pipelines/sessionreplay/shared/outputs'
import { HealthCheckResult, HealthCheckResultError, HealthCheckResultOk, PluginServerService, RedisPool } from '~/types'

import { RecordingApiOp, createRecordingApiAuthMiddleware, createReplayBlocksAuthMiddleware } from './auth'
import { ClickHouseCredential } from './clickhouse-credential'
import { RecordingApiMetrics } from './metrics'
import { BlockAdmission, ListedBlock, RecordingDeletedResult, RecordingService } from './recording-service'
import {
    DeleteRecordingsBodySchema,
    EncryptBlocksBodySchema,
    GetBlockQuerySchema,
    RecordingParamsSchema,
    ReplayBlockParamsSchema,
    TeamParamsSchema,
} from './schemas'
import { SingleFlightKeyStore } from './single-flight-keystore'
import { TimedKeyStore } from './timed-keystore'
import {
    KeyStore,
    REPLAY_BLOCK_TIERS,
    RecordingApiConfig,
    RecordingApiRole,
    RecordingBlock,
    RecordingDecryptor,
    RecordingEncryptor,
    ReplayBlockBucket,
    ReplayBlockTier,
    getDefaultRecordingApiBlocksConfig,
    parseRecordingApiRole,
    parseReplayBlockRateLimits,
} from './types'

// The browser keeps each block for 4 hours, which bounds how long a deleted recording stays readable from its cache.
// Django's sources listing, which hands out block URLs, reads the block listing uncached and reports a deletion first,
// so the player never asks for a cached block of a deleted recording.
const REPLAY_BLOCK_CACHE_CONTROL = 'private, max-age=14400, immutable'

const KEY_LOOKUP_TIMEOUT_MS = 1000
// Each Redis, DynamoDB and KMS call gives up after this, so a lookup the listing abandoned does not pile up.

function sendRecordingDeleted(res: express.Response, deletion: RecordingDeletedResult): void {
    res.status(410).json({ error: 'recording_deleted', deleted_at: deletion.deletedAt, deleted_by: deletion.deletedBy })
}

export class RecordingApi {
    private s3Client: S3Client | null = null
    private s3Bucket: string | null = null
    private s3Prefix: string | null = null
    private keyStore: KeyStore | null = null
    private decryptor: RecordingDecryptor | null = null
    private encryptor: RecordingEncryptor | null = null
    private redisPool: RedisPool | null = null
    private clickhouseClient: ClickHouseClient | null = null
    private recordingService: RecordingService | null = null
    private blockRateLimiter: KeyedRateLimiterService | null = null
    private readonly role: RecordingApiRole
    private readonly replayBlockBuckets: Record<ReplayBlockTier, ReplayBlockBucket> | null
    private publicBlockBytesInFlight = 0

    // Postgres and the outputs are only used by internal routes, so a public process passes neither.
    constructor(
        private config: RecordingApiConfig,
        private postgres?: PostgresRouter,
        private outputs?: IngestionOutputs<ReplayEventsOutput | SessionFeaturesOutput>
    ) {
        this.role = parseRecordingApiRole(config.RECORDING_API_ROLE || 'internal')
        // Only a process serving the browser route reads its limits, so a bad value cannot stop an internal pod.
        this.replayBlockBuckets = this.servesPublicRoutes
            ? parseReplayBlockRateLimits(
                  config.RECORDING_API_BLOCK_RATE_LIMITS ||
                      getDefaultRecordingApiBlocksConfig().RECORDING_API_BLOCK_RATE_LIMITS
              )
            : null
    }

    private get servesInternalRoutes(): boolean {
        return this.role !== 'public'
    }

    private get servesPublicRoutes(): boolean {
        return this.role !== 'internal'
    }

    public get service(): PluginServerService {
        return {
            id: 'recording-api',
            onShutdown: () => Promise.resolve(this.stop()),
            healthcheck: () => this.isHealthy(),
        }
    }

    async start(recordingService?: RecordingService, blockRateLimiter?: KeyedRateLimiterService): Promise<void> {
        if (recordingService) {
            this.recordingService = recordingService
            this.blockRateLimiter = blockRateLimiter ?? null
            logger.info('[RecordingApi] Started with injected RecordingService')
            return
        }

        // Load S3 settings
        const s3Region = this.config.SESSION_RECORDING_V2_S3_REGION ?? 'us-east-1'
        const s3Endpoint = this.config.SESSION_RECORDING_V2_S3_ENDPOINT ?? undefined
        const s3AccessKeyId = this.config.SESSION_RECORDING_V2_S3_ACCESS_KEY_ID
        const s3SecretAccessKey = this.config.SESSION_RECORDING_V2_S3_SECRET_ACCESS_KEY

        this.s3Bucket = this.config.SESSION_RECORDING_V2_S3_BUCKET
        this.s3Prefix = this.config.SESSION_RECORDING_V2_S3_PREFIX

        logger.info('[RecordingApi] Starting with S3 config', {
            region: s3Region,
            endpoint: s3Endpoint,
            bucket: this.s3Bucket,
            prefix: this.s3Prefix,
            hasCredentials: !!(s3AccessKeyId && s3SecretAccessKey),
        })

        const s3Config: S3ClientConfig = {
            region: s3Region,
            endpoint: s3Endpoint,
            forcePathStyle: s3Endpoint ? true : undefined,
        }

        if (s3AccessKeyId && s3SecretAccessKey) {
            s3Config.credentials = {
                accessKeyId: s3AccessKeyId,
                secretAccessKey: s3SecretAccessKey,
            }
        }

        this.s3Client = new S3Client(s3Config)

        // Bounded so a stalled Redis fails fast rather than holding requests the listing has stopped waiting for.
        const redisConfig = (name: string) => ({
            connection: {
                url: this.config.SESSION_RECORDING_API_REDIS_HOST,
                options: {
                    port: this.config.SESSION_RECORDING_API_REDIS_PORT,
                    commandTimeout: this.config.RECORDING_API_REDIS_TIMEOUT_MS,
                },
                name,
            },
            poolMinSize: this.config.REDIS_POOL_MIN_SIZE,
            poolMaxSize: this.config.REDIS_POOL_MAX_SIZE,
            acquireTimeoutMillis: this.config.RECORDING_API_REDIS_TIMEOUT_MS,
        })
        this.redisPool = createRedisPoolFromConfig(redisConfig('recording-api'))

        const keyStore: KeyStore = new SingleFlightKeyStore(
            new TimedKeyStore(
                getKeyStore(s3Region, {
                    kmsEndpoint: this.config.SESSION_RECORDING_KMS_ENDPOINT,
                    dynamoDBEndpoint: this.config.SESSION_RECORDING_DYNAMODB_ENDPOINT,
                    requestTimeoutMs: this.config.RECORDING_API_AWS_TIMEOUT_MS,
                })
            )
        )
        // In-memory caching is intentionally omitted here — a stale in-memory cache on
        // another instance would allow serving a deleted recording's data.
        // Never cache a missing key: the browser route can name a session ingestion has not keyed yet, and DynamoDB's
        // eventually consistent read can briefly miss a new key. Either cached miss would read as cleartext for a day.
        this.keyStore = new RedisCachedKeyStore(keyStore, this.redisPool, undefined, false)
        await this.keyStore.start()

        this.decryptor = getBlockDecryptor(this.keyStore)
        await this.decryptor.start()

        if (this.servesPublicRoutes) {
            this.blockRateLimiter = new KeyedRateLimiterService(
                { name: 'recording-api-replay-blocks', ttlSeconds: 60 * 60 },
                createRedisV2PoolFromConfig(redisConfig('recording-api-replay-blocks'))
            )
        }

        if (!this.servesInternalRoutes) {
            this.recordingService = new RecordingService(
                this.s3Client,
                this.s3Bucket!,
                this.s3Prefix!,
                this.keyStore,
                this.decryptor
            )
            logger.info('[RecordingApi] Started with public routes only')
            return
        }

        if (!this.outputs) {
            throw new Error('recording-api serving internal routes needs its Kafka outputs')
        }
        this.encryptor = getBlockEncryptor(this.keyStore)
        await this.encryptor.start()

        const metadataStore = new SessionMetadataStore(this.outputs)
        const featureStore = new SessionFeatureStore(this.outputs)

        // Initialize ClickHouse client for block listing queries
        const chScheme = this.config.CLICKHOUSE_SECURE ? 'https' : 'http'
        const chPort = this.config.CLICKHOUSE_SECURE ? 8443 : 8123
        this.clickhouseClient = createClickHouseClient({
            url: `${chScheme}://${this.config.CLICKHOUSE_HOST}:${chPort}`,
            username: this.config.CLICKHOUSE_USER,
            password: this.config.CLICKHOUSE_PASSWORD || undefined,
            database: this.config.CLICKHOUSE_DATABASE,
            request_timeout: 30_000,
            max_open_connections: 10,
            // Internal ClickHouse uses self-signed certs with a hostname mismatch
            ...(this.config.CLICKHOUSE_SECURE
                ? { http_agent: new https.Agent({ rejectUnauthorized: false, keepAlive: true, maxSockets: 10 }) } // nosemgrep: problem-based-packs.insecure-transport.js-node.bypass-tls-verification.bypass-tls-verification
                : {}),
        })

        // Create the service layer
        this.recordingService = new RecordingService(
            this.s3Client,
            this.s3Bucket!,
            this.s3Prefix!,
            this.keyStore,
            this.decryptor,
            metadataStore,
            featureStore,
            this.postgres,
            { client: this.clickhouseClient, credential: ClickHouseCredential.fromConfig(this.config) },
            this.encryptor
        )

        logger.info('[RecordingApi] Started successfully')
    }

    async stop(): Promise<void> {
        this.s3Client?.destroy()
        this.keyStore?.stop()
        if (this.redisPool) {
            await this.redisPool.drain()
            await this.redisPool.clear()
        }
        if (this.clickhouseClient) {
            await this.clickhouseClient.close()
        }
    }

    isHealthy(): HealthCheckResult {
        const uninitializedComponents: string[] = []

        if (!this.s3Client) {
            uninitializedComponents.push('s3Client')
        }
        if (!this.keyStore) {
            uninitializedComponents.push('keyStore')
        }
        if (!this.decryptor) {
            uninitializedComponents.push('decryptor')
        }
        if (this.servesInternalRoutes && !this.encryptor) {
            uninitializedComponents.push('encryptor')
        }

        if (uninitializedComponents.length > 0) {
            return new HealthCheckResultError('Components not initialized', {
                uninitializedComponents,
            })
        }

        return new HealthCheckResultOk()
    }

    router(): express.Router {
        const router = express.Router()

        const asyncHandler =
            (fn: (req: express.Request, res: express.Response) => Promise<void>) =>
            (req: express.Request, res: express.Response, next: express.NextFunction): Promise<void> =>
                fn(req, res).catch(next)

        const blockPath = '/api/projects/:team_id/recordings/:session_id/block'

        const blocksPath = '/api/projects/:team_id/recordings/:session_id/blocks'

        const encryptPath = '/api/projects/:team_id/recordings/:session_id/encrypt'

        if (this.servesPublicRoutes) {
            router.get(
                '/replay-blocks/:team_id/:session_id/:viewer/:ref',
                createReplayBlocksAuthMiddleware(this.config.RECORDING_API_BLOCKS_JWT_SECRET),
                asyncHandler(this.getBlockByRef)
            )
        }
        if (!this.servesInternalRoutes) {
            return router
        }

        const auth = (op: RecordingApiOp) =>
            createRecordingApiAuthMiddleware({
                jwtSecret: this.config.RECORDING_API_JWT_SECRET,
                op,
            })
        const readAuth = auth('read')
        const deleteAuth = auth('delete')
        const writeAuth = auth('write')

        // Registered before the prefix middleware so its own write scope applies instead of the delete scope.
        router.post(encryptPath, writeAuth, asyncHandler(this.encryptBlocks))

        // Mounted on the whole '/api/projects' prefix, matching what the shared-secret middleware
        // exempts, rather than on the recording routes alone. Anything under the prefix that this
        // router does not handle then still needs a valid token and gets a 401, so a route added
        // later cannot ship unauthenticated. op comes from the method: GET reads, anything mutating
        // gets the stricter delete scope. Registered before the routes so it runs first.
        router.use('/api/projects', (req, res, next) => (req.method === 'GET' ? readAuth : deleteAuth)(req, res, next))

        router.get(blockPath, asyncHandler(this.getBlock))
        router.get(blocksPath, asyncHandler(this.listBlocks))
        router.post('/api/projects/:team_id/recordings/delete', asyncHandler(this.deleteRecordings))

        return router
    }

    private getBlock = async (req: express.Request, res: express.Response): Promise<void> => {
        // Parse and validate request
        const paramsResult = RecordingParamsSchema.safeParse(req.params)
        if (!paramsResult.success) {
            res.status(400).json({ error: paramsResult.error.issues[0].message })
            return
        }

        const queryResult = GetBlockQuerySchema.safeParse(req.query)
        if (!queryResult.success) {
            res.status(400).json({ error: queryResult.error.issues[0].message })
            return
        }

        // Check service initialization
        if (!this.recordingService) {
            res.status(503).json({ error: 'S3 client not initialized' })
            return
        }

        const { team_id: teamId, session_id: sessionId } = paramsResult.data
        const { key, start_byte: startByte, end_byte: endByte, decompress } = queryResult.data

        // Validate S3 key format
        if (!this.recordingService.validateS3Key(key)) {
            res.status(400).json({ error: this.recordingService.formatS3KeyError() })
            return
        }

        // Call service
        try {
            const result = await this.recordingService.getBlock({
                sessionId,
                teamId,
                key,
                startByte,
                endByte,
                decompress,
            })

            // Serialize response
            if (!result.ok) {
                if (result.error === 'deleted') {
                    sendRecordingDeleted(res, result)
                    return
                }
                res.status(404).json({ error: 'Block not found' })
                return
            }

            const contentType = decompress ? 'application/jsonl' : 'application/octet-stream'
            res.set('Content-Type', contentType)
            res.set('Content-Length', String(Buffer.byteLength(result.data)))
            res.set('Cache-Control', 'public, max-age=2592000, immutable')
            res.send(result.data)
        } catch (error) {
            logger.error('[RecordingApi] Error fetching block from S3', {
                error: serializeError(error),
                key,
                start: startByte,
                end: endByte,
                teamId,
                sessionId,
            })
            captureException(error)
            res.status(500).json({ error: 'Failed to fetch block from S3' })
        }
    }

    private listBlocks = async (req: express.Request, res: express.Response): Promise<void> => {
        const paramsResult = RecordingParamsSchema.safeParse(req.params)
        if (!paramsResult.success) {
            res.status(400).json({ error: paramsResult.error.issues[0].message })
            return
        }

        if (!this.recordingService) {
            res.status(503).json({ error: 'Service not initialized' })
            return
        }

        const { team_id: teamId, session_id: sessionId } = paramsResult.data

        try {
            const blocks = await this.recordingService.listBlocks(sessionId, teamId)
            const annotated =
                blocks.length > 0
                    ? await this.annotateOrPlain(this.recordingService, sessionId, teamId, blocks)
                    : blocks
            if (!Array.isArray(annotated)) {
                sendRecordingDeleted(res, annotated)
                return
            }
            res.json({ blocks: annotated })
        } catch (error) {
            logger.error('[RecordingApi] Error listing blocks', {
                error: serializeError(error),
                teamId,
                sessionId,
            })
            captureException(error)
            res.status(500).json({ error: 'Failed to list blocks' })
        }
    }

    // The listing only reports a deletion and hands out refs as extras, so a key store outage or stall must not stop
    // it: the blocks still list without refs, and getBlock still returns 410.
    private async annotateOrPlain(
        service: RecordingService,
        sessionId: string,
        teamId: number,
        blocks: RecordingBlock[]
    ): Promise<RecordingDeletedResult | ListedBlock[]> {
        let timer: NodeJS.Timeout | undefined
        const timeout = new Promise<never>((_, reject) => {
            timer = setTimeout(() => reject(new Error('Key lookup timed out')), KEY_LOOKUP_TIMEOUT_MS)
        })
        try {
            return await Promise.race([service.annotateBlocks(sessionId, teamId, blocks), timeout])
        } catch (error) {
            logger.warn('[RecordingApi] Could not read the session key while listing blocks', {
                error: serializeError(error),
                teamId,
                sessionId,
            })
            return blocks
        } finally {
            clearTimeout(timer)
        }
    }

    // A browser viewer has a budget of its own. API callers share their team's budget, as Django's snapshot API limits
    // do, so a team cannot multiply it with more keys. A missing or unknown tier gets the strictest bucket.
    private replayBlockBucket(
        teamId: number,
        caller: string,
        tier: unknown
    ): { id: string; bucket: ReplayBlockBucket } {
        const known = REPLAY_BLOCK_TIERS.includes(tier as ReplayBlockTier) ? (tier as ReplayBlockTier) : 'free'
        return {
            id: known === 'browser' ? `viewer:${caller}` : `team:${teamId}`,
            bucket: this.replayBlockBuckets![known],
        }
    }

    // rateLimitGrouped allows a request that spends the bucket's last token. rateLimitMany refuses it yet still spends
    // the token, so a steady trickle at the refill rate would never get through. A Redis failure lets the request
    // through: the limit protects capacity, and the block fetch needs Redis for the key lookup anyway.
    private async isRateLimited(id: string, bucket: ReplayBlockBucket): Promise<boolean> {
        try {
            const [[, decision]] = await this.blockRateLimiter!.rateLimitGrouped([
                { id, cost: 1, bucketSize: bucket.bucketSize, refillRate: bucket.refillPerSecond },
            ])
            return decision.isRateLimited
        } catch (error) {
            RecordingApiMetrics.incrementReplayBlockRequest('rate_limit_unavailable')
            logger.warn('[RecordingApi] Block rate limit unavailable, allowing the request', {
                error: serializeError(error),
            })
            return false
        }
    }

    // Each block is read and decrypted whole in memory, so the process caps the bytes it holds at once.
    private admitPublicBlock(bytes: number): BlockAdmission {
        if (bytes > this.config.RECORDING_API_MAX_PUBLIC_BLOCK_BYTES) {
            return 'too_large'
        }
        if (this.publicBlockBytesInFlight + bytes > this.config.RECORDING_API_PUBLIC_BLOCK_BYTES_IN_FLIGHT) {
            return 'busy'
        }
        this.publicBlockBytesInFlight += bytes
        return 'ok'
    }

    private getBlockByRef = async (req: express.Request, res: express.Response): Promise<void> => {
        const paramsResult = ReplayBlockParamsSchema.safeParse(req.params)
        if (!paramsResult.success) {
            res.status(400).json({ error: paramsResult.error.issues[0].message })
            return
        }
        if (!this.recordingService) {
            res.status(503).json({ error: 'Service not initialized' })
            return
        }
        const { team_id: teamId, session_id: sessionId, ref } = paramsResult.data
        let admittedBytes = 0

        try {
            if (this.blockRateLimiter) {
                const { id, bucket } = this.replayBlockBucket(
                    teamId,
                    res.locals.replayBlocksCaller,
                    res.locals.replayBlocksTier
                )
                if (await this.isRateLimited(id, bucket)) {
                    const enforced = this.config.RECORDING_API_BLOCK_RATE_LIMIT_ENFORCED
                    RecordingApiMetrics.incrementReplayBlockRequest(enforced ? 'rate_limited' : 'rate_limited_log_only')
                    if (enforced) {
                        // The wait for one token to refill, not a fixed window.
                        res.set('Retry-After', String(Math.ceil(1 / bucket.refillPerSecond)))
                        res.status(429).json({ error: 'Too many requests' })
                        return
                    }
                }
            }

            const result = await this.recordingService.getBlockByRef(teamId, sessionId, ref, (bytes) => {
                const admission = this.admitPublicBlock(bytes)
                if (admission === 'ok') {
                    admittedBytes = bytes
                }
                return admission
            })
            if (!result.ok) {
                RecordingApiMetrics.incrementReplayBlockRequest(result.error === 'deleted' ? 'deleted' : result.error)
                if (result.error === 'deleted') {
                    sendRecordingDeleted(res, result)
                    return
                }
                if (result.error === 'too_large') {
                    res.status(413).json({ error: 'Block too large for this route' })
                    return
                }
                if (result.error === 'busy') {
                    res.set('Retry-After', '1')
                    res.status(503).json({ error: 'Busy' })
                    return
                }
                res.status(404).json({ error: 'Block not found' })
                return
            }
            RecordingApiMetrics.incrementReplayBlockRequest('ok')
            res.set('Content-Type', 'application/octet-stream')
            res.set('Content-Length', String(Buffer.byteLength(result.data)))
            res.set('Cache-Control', REPLAY_BLOCK_CACHE_CONTROL)
            // The block is attacker-influenced bytes on an app origin, so the browser must never sniff it as HTML.
            res.set('X-Content-Type-Options', 'nosniff')
            res.send(result.data)
        } catch (error) {
            RecordingApiMetrics.incrementReplayBlockRequest('error')
            logger.error('[RecordingApi] Error serving a block by ref', {
                error: serializeError(error),
                teamId,
                sessionId,
            })
            captureException(error)
            res.status(500).json({ error: 'Failed to fetch block' })
        } finally {
            this.publicBlockBytesInFlight -= admittedBytes
        }
    }

    private encryptBlocks = async (req: express.Request, res: express.Response): Promise<void> => {
        const paramsResult = RecordingParamsSchema.safeParse(req.params)
        if (!paramsResult.success) {
            res.status(400).json({ error: paramsResult.error.issues[0].message })
            return
        }

        const bodyResult = EncryptBlocksBodySchema.safeParse(req.body)
        if (!bodyResult.success) {
            res.status(400).json({ error: bodyResult.error.issues[0].message })
            return
        }

        if (!this.recordingService) {
            res.status(503).json({ error: 'Service not initialized' })
            return
        }

        const { team_id: teamId, session_id: sessionId } = paramsResult.data
        const { blocks, retention_days: retentionDays } = bodyResult.data

        try {
            const result = await this.recordingService.encryptBlocks(
                sessionId,
                teamId,
                blocks.map((b) => Buffer.from(b, 'base64')),
                retentionDays
            )
            if (!result.ok) {
                if (result.error === 'recording_exists') {
                    res.status(409).json({ error: 'recording_exists' })
                    return
                }
                if (result.error === 'key_unavailable') {
                    res.status(503).json({ error: 'key_unavailable' })
                    return
                }
                sendRecordingDeleted(res, result)
                return
            }
            res.json({ blocks: result.blocks.map((b) => b.toString('base64')) })
        } catch (error) {
            logger.error('[RecordingApi] Error encrypting blocks', {
                error: serializeError(error),
                teamId,
                sessionId,
            })
            captureException(error)
            res.status(500).json({ error: 'Failed to encrypt blocks' })
        }
    }

    private deleteRecordings = async (req: express.Request, res: express.Response): Promise<void> => {
        const paramsResult = TeamParamsSchema.safeParse(req.params)
        if (!paramsResult.success) {
            res.status(400).json({ error: paramsResult.error.issues[0].message })
            return
        }

        const bodyResult = DeleteRecordingsBodySchema.safeParse(req.body)
        if (!bodyResult.success) {
            res.status(400).json({ error: bodyResult.error.issues[0].message })
            return
        }

        if (!this.recordingService) {
            res.status(503).json({ error: 'Service not initialized' })
            return
        }

        const { team_id: teamId } = paramsResult.data
        const { session_ids: sessionIds, deleted_by: deletedBy } = bodyResult.data

        try {
            const result = await this.recordingService.deleteRecordings(sessionIds, teamId, deletedBy)
            res.json(result)
        } catch (error) {
            logger.error('[RecordingApi] Error in delete recordings', {
                error: serializeError(error),
                teamId,
            })
            captureException(error)
            res.status(500).json({ error: 'Failed to delete recordings' })
        }
    }
}
