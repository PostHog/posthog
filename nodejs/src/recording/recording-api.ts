import { GetObjectCommand, S3Client } from '@aws-sdk/client-s3'
import express from 'ultimate-express'

import { HealthCheckResult, HealthCheckResultError, HealthCheckResultOk, Hub, PluginServerService } from '../types'
import { logger } from '../utils/logger'
import { BaseKeyStore, getKeyStore } from './keystore'
import { BaseRecordingDecryptor, getBlockDecryptor } from './recording-io'

interface ParsedS3Uri {
    bucket: string
    key: string
    range: string
}

export class RecordingApi {
    private s3Client: S3Client | null = null
    private keyStore: BaseKeyStore | null = null
    private decryptor: BaseRecordingDecryptor | null = null

    constructor(private hub: Hub) {}

    public get service(): PluginServerService {
        return {
            id: 'recording-api',
            onShutdown: async () => await this.stop(),
            healthcheck: () => this.isHealthy(),
        }
    }

    async start(): Promise<void> {
        const region = this.hub.SESSION_RECORDING_V2_S3_REGION ?? 'us-east-1'

        this.s3Client = new S3Client({
            region,
            endpoint: this.hub.SESSION_RECORDING_V2_S3_ENDPOINT ?? undefined,
            forcePathStyle: this.hub.SESSION_RECORDING_V2_S3_ENDPOINT ? true : undefined,
        })

        this.keyStore = await getKeyStore(this.hub, region)
        this.decryptor = await getBlockDecryptor(this.keyStore)
    }

    async stop(): Promise<void> {
        this.s3Client?.destroy()
        this.s3Client = null
        await this.keyStore?.destroy()
        this.keyStore = null
        this.decryptor = null
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

    private parseS3Uri(uri: string): ParsedS3Uri | null {
        try {
            const url = new URL(uri)
            if (url.protocol !== 's3:') {
                return null
            }

            const bucket = url.hostname
            const key = url.pathname.slice(1) // Remove leading slash
            const range = url.searchParams.get('range')

            if (!range) {
                return null
            }

            return { bucket, key, range }
        } catch {
            return null
        }
    }

    private getBlock = async (req: express.Request, res: express.Response): Promise<void> => {
        const { team_id, session_id } = req.params
        const { uri } = req.query

        if (!uri || typeof uri !== 'string') {
            res.status(400).json({ error: 'Missing or invalid uri query parameter' })
            return
        }

        const parsed = this.parseS3Uri(uri)
        if (!parsed) {
            res.status(400).json({
                error: 'Invalid S3 URI format. Expected: s3://bucket/key?range=bytes=start-end (range is required)',
            })
            return
        }

        if (!this.s3Client) {
            res.status(503).json({ error: 'S3 client not initialized' })
            return
        }

        if (!this.decryptor) {
            res.status(503).json({ error: 'Decryptor not initialized' })
            return
        }

        try {
            const command = new GetObjectCommand({
                Bucket: parsed.bucket,
                Key: parsed.key,
                Range: parsed.range,
            })

            const response = await this.s3Client.send(command)

            if (!response.Body) {
                res.status(404).json({ error: 'Block not found' })
                return
            }

            const bodyContents = await response.Body.transformToByteArray()
            const decrypted = await this.decryptor.decryptBlock(
                session_id,
                parseInt(team_id),
                Buffer.from(bodyContents)
            )

            res.set('Content-Type', 'application/octet-stream')
            res.set('Content-Length', String(decrypted.length))
            res.send(decrypted)
        } catch (error) {
            logger.error('[RecordingApi] Error fetching block from S3', { error, uri, team_id, session_id })
            res.status(500).json({ error: 'Failed to fetch block from S3' })
        }
    }

    private deleteRecording = async (req: express.Request, res: express.Response): Promise<void> => {
        const { team_id, session_id } = req.params

        if (!this.keyStore) {
            res.status(503).json({ error: 'KeyStore not initialized' })
            return
        }

        try {
            const deleted = await this.keyStore.deleteKey(session_id, parseInt(team_id))
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
