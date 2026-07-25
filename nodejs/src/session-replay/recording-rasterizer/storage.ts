import { S3Client } from '@aws-sdk/client-s3'
import { Upload } from '@aws-sdk/lib-storage'
import * as fs from 'fs'
import { HttpsProxyAgent } from 'https-proxy-agent'

import { sanitizeForUTF8 } from '~/common/utils/strings'

import { config } from './config'
import { RasterizationError } from './errors'
import { createLogger } from './logger'

const log = createLogger()

function undecodableS3ResponseError(err: unknown): RasterizationError | null {
    if (!(err instanceof Error) || !/Deserialization error|is not expected/i.test(err.message)) {
        return null
    }

    // The AWS SDK stashes the raw response the XML parser choked on under $response, a property its
    // public error type omits, so read it defensively to recover the real status and body.
    const { statusCode, body } = (err as { $response?: { statusCode?: number; body?: unknown } }).$response ?? {}
    const details = [`status ${statusCode ?? 'unknown'}`]
    if (typeof body === 'string' && body.length > 0) {
        details.push(`body: ${sanitizeForUTF8(body.slice(0, 500))}`)
    }
    // Without a status we cannot tell a client error from a server one, so retry rather than fail the render.
    const retryable = statusCode === undefined || statusCode >= 500 || statusCode === 429
    return new RasterizationError(
        `S3 upload returned an undecodable (non-XML) response (${details.join(', ')})`,
        retryable,
        'S3_UPLOAD_UNDECODABLE_RESPONSE',
        err
    )
}

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
            // S3 goes through the proxy, but credential refresh must dial direct
            // (the SDK does not honor NO_PROXY). The default credential provider
            // does this on its own, so long as we don't hand it our proxied
            // requestHandler.
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

    try {
        await upload.done()
    } catch (err) {
        const undecodable = undecodableS3ResponseError(err)
        if (!undecodable) {
            throw err
        }
        log.warn({ err, bucket, key }, 'S3 upload returned an undecodable response')
        throw undecodable
    }

    return `s3://${bucket}/${key}`
}
