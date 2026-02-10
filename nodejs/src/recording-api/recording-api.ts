import { S3Client, S3ClientConfig } from '@aws-sdk/client-s3'
import express from 'ultimate-express'

import { RetentionService } from '../session-recording/retention/retention-service'
import { TeamService } from '../session-recording/teams/team-service'
import {
    HealthCheckResult,
    HealthCheckResultError,
    HealthCheckResultOk,
    PluginServerService,
    RedisPool,
} from '../types'
import { createRedisPoolFromConfig } from '../utils/db/redis'
import { logger } from '../utils/logger'
import { RedisCachedKeyStore } from './cache'
import { getBlockDecryptor } from './crypto'
import { getKeyStore } from './keystore'
import { RecordingService } from './recording-service'
import { GetBlockQuerySchema, RecordingParamsSchema } from './schemas'
import { KeyStore, RecordingApiHub, RecordingDecryptor } from './types'

export class RecordingApi {
    private s3Client: S3Client | null = null
    private s3Bucket: string | null = null
    private s3Prefix: string | null = null
    private keyStore: KeyStore | null = null
    private decryptor: RecordingDecryptor | null = null
    private redisPool: RedisPool | null = null
    private recordingService: RecordingService | null = null

    constructor(private hub: RecordingApiHub) {}

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
        const s3Region = this.hub.SESSION_RECORDING_V2_S3_REGION ?? 'us-east-1'
        const s3Endpoint = this.hub.SESSION_RECORDING_V2_S3_ENDPOINT ?? undefined
        const s3AccessKeyId = this.hub.SESSION_RECORDING_V2_S3_ACCESS_KEY_ID
        const s3SecretAccessKey = this.hub.SESSION_RECORDING_V2_S3_SECRET_ACCESS_KEY

        this.s3Bucket = this.hub.SESSION_RECORDING_V2_S3_BUCKET
        this.s3Prefix = this.hub.SESSION_RECORDING_V2_S3_PREFIX

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

        const teamService = new TeamService(this.hub.postgres)
        this.redisPool = createRedisPoolFromConfig({
            connection: {
                url: this.hub.SESSION_RECORDING_API_REDIS_HOST,
                options: { port: this.hub.SESSION_RECORDING_API_REDIS_PORT },
                name: 'recording-api',
            },
            poolMinSize: this.hub.REDIS_POOL_MIN_SIZE,
            poolMaxSize: this.hub.REDIS_POOL_MAX_SIZE,
        })
        const retentionService = new RetentionService(this.redisPool, teamService)

        const keyStore: KeyStore = getKeyStore(teamService, retentionService, s3Region, {
            kmsEndpoint: this.hub.SESSION_RECORDING_KMS_ENDPOINT,
            dynamoDBEndpoint: this.hub.SESSION_RECORDING_DYNAMODB_ENDPOINT,
        })
        // In-memory caching is intentionally omitted here — a stale in-memory cache on
        // another instance would allow serving a deleted recording's data.
        this.keyStore = new RedisCachedKeyStore(keyStore, this.redisPool)
        await this.keyStore.start()

        this.decryptor = getBlockDecryptor(this.keyStore)
        await this.decryptor.start()

        // Create the service layer
        this.recordingService = new RecordingService(
            this.s3Client,
            this.s3Bucket!,
            this.s3Prefix!,
            this.keyStore,
            this.decryptor
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

        router.get('/api/projects/:team_id/recordings/:session_id/block', asyncHandler(this.getBlock))
        router.delete('/api/projects/:team_id/recordings/:session_id', asyncHandler(this.deleteRecording))

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
        const { key, start: startByte, end: endByte } = queryResult.data

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
            })

            // Serialize response
            if (!result.ok) {
                if (result.error === 'deleted') {
                    res.status(410).json({
                        error: 'Recording has been deleted',
                        deleted_at: result.deletedAt,
                    })
                    return
                }
                res.status(404).json({ error: 'Block not found' })
                return
            }

            res.set('Content-Type', 'application/octet-stream')
            res.set('Content-Length', String(result.data.length))
            res.set('Cache-Control', 'public, max-age=2592000, immutable')
            res.send(result.data)
        } catch (error) {
            logger.error('[RecordingApi] Error fetching block from S3', {
                error,
                key,
                start: startByte,
                end: endByte,
                teamId,
                sessionId,
            })
            res.status(500).json({ error: 'Failed to fetch block from S3' })
        }
    }

    private deleteRecording = async (req: express.Request, res: express.Response): Promise<void> => {
        // Parse and validate request
        const paramsResult = RecordingParamsSchema.safeParse(req.params)
        if (!paramsResult.success) {
            res.status(400).json({ error: paramsResult.error.issues[0].message })
            return
        }

        // Check service initialization
        if (!this.recordingService) {
            res.status(503).json({ error: 'KeyStore not initialized' })
            return
        }

        const { team_id: teamId, session_id: sessionId } = paramsResult.data

        // Call service
        try {
            const result = await this.recordingService.deleteRecording(sessionId, teamId)

            // Serialize response
            if (!result.ok) {
                if (result.error === 'already_deleted') {
                    res.status(410).json({
                        error: 'Recording has already been deleted',
                        deleted_at: result.deletedAt,
                    })
                    return
                }
                res.status(404).json({ error: 'Recording key not found' })
                return
            }

            res.json({ team_id: teamId, session_id: sessionId, status: 'deleted' })
        } catch (error) {
            logger.error('[RecordingApi] Error deleting recording key', { error, teamId, sessionId })
            res.status(500).json({ error: 'Failed to delete recording key' })
        }
    }
}
