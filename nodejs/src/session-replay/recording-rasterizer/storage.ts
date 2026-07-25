import { S3Client } from '@aws-sdk/client-s3'
import { Upload } from '@aws-sdk/lib-storage'
import * as fs from 'fs'
import { HttpsProxyAgent } from 'https-proxy-agent'

import { config } from './config'
import { RasterizationError } from './errors'
import { createLogger } from './logger'

const log = createLogger()

function toUploadError(err: unknown, target: string): RasterizationError {
    // The AWS SDK keeps the HTTP response off its public error type and hangs it on a non-enumerable
    // $response instead. When it could not parse the body at all, because a proxy or gateway answered with
    // plaintext or an HTML error page rather than S3's XML, $response.body holds that raw body and the
    // error the SDK raises describes nothing but its own parser's confusion. Retryability is untouched:
    // the workflow's retry policy keeps deciding, as it does for any other upload failure.
    const { statusCode, body } = (err as { $response?: { statusCode?: number; body?: unknown } })?.$response ?? {}
    const reason = err instanceof Error ? err.message : String(err)
    const responseBody = typeof body === 'string' ? `, response body: ${body.slice(0, 500)}` : ''
    return new RasterizationError(
        `S3 upload to ${target} failed (status ${statusCode ?? 'unknown'}): ${reason}${responseBody}`,
        true,
        'S3_UPLOAD_FAILED',
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

    const target = `s3://${bucket}/${key}`
    try {
        await upload.done()
    } catch (err) {
        throw toUploadError(err, target)
    }

    return target
}
