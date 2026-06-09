import { S3Client } from '@aws-sdk/client-s3'
import { defaultProvider } from '@aws-sdk/credential-provider-node'
import { Upload } from '@aws-sdk/lib-storage'
import * as fs from 'fs'
import { HttpsProxyAgent } from 'https-proxy-agent'

import { config } from './config'
import { createLogger } from './logger'

const log = createLogger()

let s3Client: S3Client | null = null

function resolveProxyUrl(): string | null {
    const upstream =
        process.env.HTTPS_PROXY || process.env.HTTP_PROXY || process.env.https_proxy || process.env.http_proxy
    if (!upstream) {
        return null
    }
    const killed = ['false', '0', 'no', 'off'].includes((process.env.RASTERIZER_USE_PROXY ?? '').trim().toLowerCase())
    if (killed) {
        log.warn(
            { RASTERIZER_USE_PROXY: process.env.RASTERIZER_USE_PROXY },
            'RASTERIZER_USE_PROXY disables egress proxy — s3 will dial direct'
        )
        return null
    }
    return upstream
}

function getS3Client(): S3Client {
    if (!s3Client) {
        const proxyUrl = resolveProxyUrl()
        const requestHandler = proxyUrl ? { httpsAgent: new HttpsProxyAgent(proxyUrl) } : undefined
        s3Client = new S3Client({
            region: config.s3Region,
            ...(config.s3Endpoint ? { endpoint: config.s3Endpoint, forcePathStyle: true } : {}),
            ...(requestHandler ? { requestHandler } : {}),
            // Route the IRSA credential-refresh STS call through the proxy too.
            // The SDK's default credential provider spawns an internal STSClient
            // that does NOT inherit our requestHandler — pass clientConfig so it
            // does. Without this, S3 goes via smokescreen but STS dials direct.
            ...(requestHandler ? { credentials: defaultProvider({ clientConfig: { requestHandler } }) } : {}),
        })
    }
    return s3Client
}

const FORMAT_META: Record<string, { ext: string; contentType: string }> = {
    mp4: { ext: 'mp4', contentType: 'video/mp4' },
    webm: { ext: 'webm', contentType: 'video/webm' },
    gif: { ext: 'gif', contentType: 'image/gif' },
}

export async function uploadToS3(
    localPath: string,
    bucket: string,
    keyPrefix: string,
    id: string,
    format: 'mp4' | 'webm' | 'gif' = 'mp4',
    onProgress?: () => void
): Promise<string> {
    const { ext, contentType } = FORMAT_META[format] || FORMAT_META.mp4
    const key = `${keyPrefix}/${id}.${ext}`

    const upload = new Upload({
        client: getS3Client(),
        params: {
            Bucket: bucket,
            Key: key,
            Body: fs.createReadStream(localPath),
            ContentType: contentType,
        },
    })

    if (onProgress) {
        upload.on('httpUploadProgress', () => onProgress())
    }

    await upload.done()

    return `s3://${bucket}/${key}`
}
