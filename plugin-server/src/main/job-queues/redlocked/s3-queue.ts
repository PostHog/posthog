import { S3 } from 'aws-sdk'
import { randomBytes } from 'crypto'
import { DateTime } from 'luxon'
import { gunzipSync, gzipSync } from 'zlib'

import { EnqueuedJob, PluginsServerConfig } from '../../../types'
import { S3Wrapper } from '../../../utils/db/s3-wrapper'
import { UUIDT } from '../../../utils/utils'
import { JobQueueBase } from '../job-queue-base'

const S3_POLL_INTERVAL = 5

export class S3Queue extends JobQueueBase {
    serverConfig: PluginsServerConfig
    s3Wrapper: S3Wrapper | null

    constructor(serverConfig: PluginsServerConfig) {
        super()
        this.serverConfig = serverConfig
        this.s3Wrapper = null
        this.intervalSeconds = S3_POLL_INTERVAL
    }

    // producer

    async connectProducer(): Promise<void> {
        await this.connectS3()
    }

    async enqueue(retry: EnqueuedJob): Promise<void> {
        if (!this.s3Wrapper) {
            throw new Error('S3 object not initialized')
        }
        const date = new Date(retry.timestamp).toISOString()
        const [day, time] = date.split('T')
        const dayTime = `${day.split('-').join('')}-${time.split(':').join('')}`
        const suffix = randomBytes(8).toString('hex')

        await this.s3Wrapper.upload({
            Bucket: this.serverConfig.JOB_QUEUE_S3_BUCKET_NAME,
            Key: `${this.serverConfig.JOB_QUEUE_S3_PREFIX || ''}${day}/${dayTime}-${suffix}.json.gz`,
            Body: gzipSync(Buffer.from(JSON.stringify(retry), 'utf8')),
        })
    }

    disconnectProducer(): void {
        // nothing to disconnect
    }

    // consumer

    async readState(): Promise<boolean> {
        if (!this.s3Wrapper) {
            throw new Error('S3 object not initialized')
        }
        const response = await this.listObjects()
        if (response.length > 0) {
            for (const filename of response) {
                const object = await this.s3Wrapper?.getObject({
                    Bucket: this.serverConfig.JOB_QUEUE_S3_BUCKET_NAME,
                    Key: filename,
                })
                if (object?.Body) {
                    const job: EnqueuedJob = JSON.parse(gunzipSync(object.Body as Buffer).toString('utf8'))
                    await this.onJob?.([job])
                    await this.s3Wrapper?.deleteObject({
                        Bucket: this.serverConfig.JOB_QUEUE_S3_BUCKET_NAME,
                        Key: filename,
                    })
                }
            }
        }
        return response.length > 0
    }

    // S3 connection utils

    async connectS3(): Promise<void> {
        if (!this.s3Wrapper) {
            this.s3Wrapper = await this.getS3Wrapper()
        }
    }

    private async listObjects(s3Wrapper = this.s3Wrapper): Promise<any[]> {
        if (!s3Wrapper) {
            throw new Error('S3 object not initialized')
        }
        const response = await s3Wrapper.listObjectsV2({
            Bucket: this.serverConfig.JOB_QUEUE_S3_BUCKET_NAME,
            Prefix: this.serverConfig.JOB_QUEUE_S3_PREFIX,
            MaxKeys: 100,
        })

        const now = DateTime.utc()

        return (response.Contents || [])
            .filter(({ Key }) => {
                // Key: `${this.serverConfig.JOB_QUEUE_S3_PREFIX || ''}${day}/${dayTime}-${suffix}.json.gz`,
                const filename = (Key || '').substring(this.serverConfig.JOB_QUEUE_S3_PREFIX.length).split('/')[1]
                const match = filename.match(
                    /^([0-9]{4})([0-9]{2})([0-9]{2})\-([0-9]{2})([0-9]{2})([0-9]{2})\.([0-9]+)Z\-[a-f0-9]+\.json\.gz$/
                )
                if (match) {
                    const [year, month, day, hour, minute, second, millisecond] = match
                        .slice(1)
                        .map((num) => parseInt(num))
                    const date = DateTime.utc(year, month, day, hour, minute, second, millisecond)
                    if (date <= now) {
                        return true
                    }
                }
                return false
            })
            .map(({ Key }) => Key)
    }

    private async getS3Wrapper(): Promise<S3Wrapper> {
        if (!this.serverConfig.JOB_QUEUE_S3_AWS_ACCESS_KEY) {
            throw new Error('AWS access key missing!')
        }
        if (!this.serverConfig.JOB_QUEUE_S3_AWS_SECRET_ACCESS_KEY) {
            throw new Error('AWS secret access key missing!')
        }
        if (!this.serverConfig.JOB_QUEUE_S3_AWS_REGION) {
            throw new Error('AWS region missing!')
        }
        if (!this.serverConfig.JOB_QUEUE_S3_BUCKET_NAME) {
            throw new Error('S3 bucket name missing!')
        }

        const s3Wrapper = new S3Wrapper({
            accessKeyId: this.serverConfig.JOB_QUEUE_S3_AWS_ACCESS_KEY,
            secretAccessKey: this.serverConfig.JOB_QUEUE_S3_AWS_SECRET_ACCESS_KEY,
            region: this.serverConfig.JOB_QUEUE_S3_AWS_REGION,
        })

        await this.testS3Connection(s3Wrapper)

        return s3Wrapper
    }

    private async testS3Connection(s3Wrapper: S3Wrapper): Promise<void> {
        const filename = `${this.serverConfig.JOB_QUEUE_S3_PREFIX || ''}CONNTEST/${new UUIDT()}.test`
        await s3Wrapper.listObjectsV2({
            Bucket: this.serverConfig.JOB_QUEUE_S3_BUCKET_NAME,
            Prefix: this.serverConfig.JOB_QUEUE_S3_PREFIX,
            MaxKeys: 2,
        })
        await s3Wrapper.upload({
            Bucket: this.serverConfig.JOB_QUEUE_S3_BUCKET_NAME,
            Key: filename,
            Body: 'test',
        })
        const object = await s3Wrapper.getObject({
            Bucket: this.serverConfig.JOB_QUEUE_S3_BUCKET_NAME,
            Key: filename,
        })
        await s3Wrapper.deleteObject({
            Bucket: this.serverConfig.JOB_QUEUE_S3_BUCKET_NAME,
            Key: filename,
        })
        if (object?.Body?.toString() !== 'test') {
            throw new Error('Read object did not equal written object')
        }
    }
}
