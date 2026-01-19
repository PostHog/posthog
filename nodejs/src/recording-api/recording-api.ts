import { GetObjectCommand, S3Client, S3ClientConfig } from '@aws-sdk/client-s3'
import express from 'ultimate-express'

import { RetentionService } from '../session-recording/retention/retention-service'
import { TeamService } from '../session-recording/teams/team-service'
import {
    HealthCheckResult,
    HealthCheckResultError,
    HealthCheckResultOk,
    Hub,
    PluginServerService,
    RedisPool,
} from '../types'
import { createRedisPoolFromConfig } from '../utils/db/redis'
import { logger } from '../utils/logger'
import { BaseKeyStore, getKeyStore } from './keystore'
import { BaseRecordingDecryptor, getBlockDecryptor } from './recording-io'

export class RecordingApi {
    private s3Client: S3Client | null = null
    private s3Bucket: string | null = null
    private keyStore: BaseKeyStore | null = null
    private decryptor: BaseRecordingDecryptor | null = null
    private keystoreRedisPool: RedisPool | null = null

    constructor(private hub: Hub) {}

    public get service(): PluginServerService {
        return {
            id: 'recording-api',
            onShutdown: () => Promise.resolve(this.stop()),
            healthcheck: () => this.isHealthy(),
        }
    }

    async start(): Promise<void> {
        // Load S3 settings
        const s3Region = this.hub.SESSION_RECORDING_V2_S3_REGION ?? 'us-east-1'
        const s3Endpoint = this.hub.SESSION_RECORDING_V2_S3_ENDPOINT ?? undefined
        const s3AccessKeyId = this.hub.SESSION_RECORDING_V2_S3_ACCESS_KEY_ID
        const s3SecretAccessKey = this.hub.SESSION_RECORDING_V2_S3_SECRET_ACCESS_KEY

        this.s3Bucket = this.hub.SESSION_RECORDING_V2_S3_BUCKET

        logger.info('[RecordingApi] Starting with S3 config', {
            region: s3Region,
            endpoint: s3Endpoint,
            bucket: this.s3Bucket,
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
        const redisPool = createRedisPoolFromConfig({
            connection: { url: this.hub.REDIS_URL, name: 'recording-api' },
            poolMinSize: this.hub.REDIS_POOL_MIN_SIZE,
            poolMaxSize: this.hub.REDIS_POOL_MAX_SIZE,
        })
        const retentionService = new RetentionService(redisPool, teamService)

        // Create a separate Redis pool for the keystore cache
        // Redis caching is enabled for the Recording API to reduce DynamoDB reads
        this.keystoreRedisPool = createRedisPoolFromConfig({
            connection: { url: this.hub.REDIS_URL, name: 'recording-api-keystore' },
            poolMinSize: this.hub.REDIS_POOL_MIN_SIZE,
            poolMaxSize: this.hub.REDIS_POOL_MAX_SIZE,
        })

        this.keyStore = getKeyStore(teamService, retentionService, s3Region, {
            redisPool: this.keystoreRedisPool,
            redisCacheEnabled: true,
            kmsEndpoint: this.hub.SESSION_RECORDING_KMS_ENDPOINT,
            dynamoDBEndpoint: this.hub.SESSION_RECORDING_DYNAMODB_ENDPOINT,
        })
        await this.keyStore.start()
        this.decryptor = getBlockDecryptor(this.keyStore)
        await this.decryptor.start()

        logger.info('[RecordingApi] Started successfully')
    }

    async stop(): Promise<void> {
        this.s3Client?.destroy()
        this.keyStore?.stop()
        if (this.keystoreRedisPool) {
            await this.keystoreRedisPool.drain()
            await this.keystoreRedisPool.clear()
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
        const { team_id, session_id } = req.params
        const { key, start, end } = req.query

        logger.info('[RecordingApi] getBlock request', {
            team_id,
            session_id,
            key,
            start,
            end,
        })

        if (!key || typeof key !== 'string') {
            res.status(400).json({ error: 'Missing or invalid key query parameter' })
            return
        }

        if (!start || typeof start !== 'string') {
            res.status(400).json({ error: 'Missing or invalid start query parameter' })
            return
        }

        if (!end || typeof end !== 'string') {
            res.status(400).json({ error: 'Missing or invalid end query parameter' })
            return
        }

        const startByte = parseInt(start, 10)
        const endByte = parseInt(end, 10)

        if (isNaN(startByte) || isNaN(endByte)) {
            res.status(400).json({ error: 'start and end must be valid integers' })
            return
        }

        if (!this.s3Client || !this.s3Bucket) {
            res.status(503).json({ error: 'S3 client not initialized' })
            return
        }

        if (!this.decryptor) {
            res.status(503).json({ error: 'Decryptor not initialized' })
            return
        }

        try {
            const command = new GetObjectCommand({
                Bucket: this.s3Bucket,
                Key: key,
                Range: `bytes=${startByte}-${endByte}`,
            })

            logger.debug('[RecordingApi] Fetching from S3', {
                bucket: this.s3Bucket,
                key,
                range: `bytes=${startByte}-${endByte}`,
            })

            const response = await this.s3Client.send(command)

            if (!response.Body) {
                logger.debug('[RecordingApi] S3 returned no body', { key })
                res.status(404).json({ error: 'Block not found' })
                return
            }

            const bodyContents = await response.Body.transformToByteArray()
            logger.debug('[RecordingApi] S3 returned data', {
                key,
                bytesReceived: bodyContents.length,
            })

            const decrypted = await this.decryptor.decryptBlock(
                session_id,
                parseInt(team_id),
                Buffer.from(bodyContents)
            )

            logger.debug('[RecordingApi] Decrypted block', {
                session_id,
                team_id,
                inputSize: bodyContents.length,
                outputSize: decrypted.length,
            })

            res.set('Content-Type', 'application/octet-stream')
            res.set('Content-Length', String(decrypted.length))
            res.send(decrypted)
        } catch (error) {
            logger.error('[RecordingApi] Error fetching block from S3', {
                error,
                key,
                start: startByte,
                end: endByte,
                team_id,
                session_id,
            })
            res.status(500).json({ error: 'Failed to fetch block from S3' })
        }
    }

    private deleteRecording = async (req: express.Request, res: express.Response): Promise<void> => {
        const { team_id, session_id } = req.params

        logger.info('[RecordingApi] deleteRecording request', { team_id, session_id })

        if (!this.keyStore) {
            res.status(503).json({ error: 'KeyStore not initialized' })
            return
        }

        try {
            const deleted = await this.keyStore.deleteKey(session_id, parseInt(team_id))
            logger.debug('[RecordingApi] deleteKey result', { team_id, session_id, deleted })
            if (deleted) {
                res.json({ team_id, session_id, status: 'deleted' })
            } else {
                res.status(404).json({ error: 'Recording key not found' })
            }
        } catch (error) {
            logger.error('[RecordingApi] Error deleting recording key', { error, team_id, session_id })
            res.status(500).json({ error: 'Failed to delete recording key' })
        }
    }
}
