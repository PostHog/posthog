import { S3Client, S3ClientConfig } from '@aws-sdk/client-s3'
import { ClickHouseClient, createClient as createClickHouseClient } from '@clickhouse/client'
import https from 'https'
import express from 'ultimate-express'

import { IngestionOutputs } from '../../ingestion/outputs/ingestion-outputs'
import {
    HealthCheckResult,
    HealthCheckResultError,
    HealthCheckResultOk,
    PluginServerService,
    RedisPool,
} from '../../types'
import { PostgresRouter } from '../../utils/db/postgres'
import { createRedisPoolFromConfig } from '../../utils/db/redis'
import { logger, serializeError } from '../../utils/logger'
import { captureException } from '../../utils/posthog'
import { getBlockDecryptor } from '../shared/crypto'
import { SessionFeatureStore } from '../shared/features/session-feature-store'
import { getKeyStore } from '../shared/keystore'
import { RedisCachedKeyStore } from '../shared/keystore/cache'
import { SessionMetadataStore } from '../shared/metadata/session-metadata-store'
import { ReplayEventsOutput, SessionFeaturesOutput } from '../shared/outputs'
import { RetentionService } from '../shared/retention/retention-service'
import { TeamService } from '../shared/teams/team-service'
import { RecordingService } from './recording-service'
import { DeleteRecordingsBodySchema, GetBlockQuerySchema, RecordingParamsSchema, TeamParamsSchema } from './schemas'
import { KeyStore, RecordingApiConfig, RecordingDecryptor } from './types'

export class RecordingApi {
    private s3Client: S3Client | null = null
    private s3Bucket: string | null = null
    private s3Prefix: string | null = null
    private keyStore: KeyStore | null = null
    private decryptor: RecordingDecryptor | null = null
    private redisPool: RedisPool | null = null
    private clickhouseClient: ClickHouseClient | null = null
    private recordingService: RecordingService | null = null

    constructor(
        private config: RecordingApiConfig,
        private postgres: PostgresRouter,
        private outputs: IngestionOutputs<ReplayEventsOutput | SessionFeaturesOutput>
    ) {}

    public get service(): PluginServerService {
        return {
            id: 'recording-api',
            onShutdown: () => Promise.resolve(this.stop()),
            healthcheck: () => this.isHealthy(),
        }
    }

    async start(recordingService?: RecordingService): Promise<void> {
        if (recordingService) {
            this.recordingService = recordingService
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

        const teamService = new TeamService(this.postgres)
        this.redisPool = createRedisPoolFromConfig({
            connection: {
                url: this.config.SESSION_RECORDING_API_REDIS_HOST,
                options: { port: this.config.SESSION_RECORDING_API_REDIS_PORT },
                name: 'recording-api',
            },
            poolMinSize: this.config.REDIS_POOL_MIN_SIZE,
            poolMaxSize: this.config.REDIS_POOL_MAX_SIZE,
        })
        const retentionService = new RetentionService(this.redisPool, teamService)

        const keyStore: KeyStore = getKeyStore(retentionService, s3Region, {
            kmsEndpoint: this.config.SESSION_RECORDING_KMS_ENDPOINT,
            dynamoDBEndpoint: this.config.SESSION_RECORDING_DYNAMODB_ENDPOINT,
        })
        // In-memory caching is intentionally omitted here — a stale in-memory cache on
        // another instance would allow serving a deleted recording's data.
        this.keyStore = new RedisCachedKeyStore(keyStore, this.redisPool)
        await this.keyStore.start()

        this.decryptor = getBlockDecryptor(this.keyStore)
        await this.decryptor.start()

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
            this.clickhouseClient
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
                    res.status(410).json({
                        error: 'recording_deleted',
                        deleted_at: result.deletedAt,
                        deleted_by: result.deletedBy,
                    })
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
            res.json({ blocks })
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
