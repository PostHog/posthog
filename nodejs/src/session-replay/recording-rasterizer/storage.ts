import { S3Client } from '@aws-sdk/client-s3'
import { defaultProvider } from '@aws-sdk/credential-provider-node'
import { Upload } from '@aws-sdk/lib-storage'
import { NodeHttpHandler } from '@smithy/node-http-handler'
import * as fs from 'fs'
import { HttpsProxyAgent } from 'https-proxy-agent'

import { config } from './config'
import { resolveEgressProxyUrl } from './egress-proxy'
import { RasterizationError } from './errors'
import { createLogger } from './logger'

const log = createLogger()

// The AWS SDK attaches $responseBodyText to an error only when it could not parse the response body at
// all, and hangs the HTTP response itself on a non-enumerable $response. Both are absent from its public
// error type. That pair identifies the one failure worth translating: a proxy or gateway answering with
// plaintext or an HTML error page instead of S3's XML, where the error the SDK raises describes its own
// parser rather than the request, and the raw body is the only place the real reason survives.
type UndecodableS3Response = {
    $responseBodyText?: string
    $response?: { statusCode?: number }
}

function undecodableResponse(err: unknown): { status?: number; body: string } | null {
    const { $responseBodyText, $response } = (err ?? {}) as UndecodableS3Response
    if (typeof $responseBodyText !== 'string') {
        return null
    }
    return { status: $response?.statusCode, body: $responseBodyText.slice(0, 500) }
}

let s3Client: S3Client | null = null

function getS3Client(): S3Client {
    if (!s3Client) {
        const proxyUrl = resolveEgressProxyUrl()
        const requestHandler = proxyUrl ? { httpsAgent: new HttpsProxyAgent(proxyUrl) } : undefined
        s3Client = new S3Client({
            region: config.s3Region,
            ...(config.s3Endpoint ? { endpoint: config.s3Endpoint, forcePathStyle: true } : {}),
            ...(requestHandler ? { requestHandler } : {}),
            // DO NOT REMOVE this credentials override. The SDK's nested STS client inherits
            // the parent's requestHandler (parentClientConfig); without an explicit unproxied
            // handler, IRSA STS credential refresh gets routed through the proxy, which rejects
            // it (407) and fails every S3 upload.
            ...(requestHandler
                ? { credentials: defaultProvider({ clientConfig: { requestHandler: new NodeHttpHandler() } }) }
                : {}),
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
        const undecodable = undecodableResponse(err)
        if (!undecodable) {
            // Raw SDK errors would surface as UNKNOWN in the error metrics and as untyped
            // ApplicationFailures to the workflow. Always retryable: a 403 can be a transient
            // credential-refresh race, and a wasted retry is cheaper than discarding a finished
            // render over a misclassified permanent failure.
            const status = (err as { $metadata?: { httpStatusCode?: number } })?.$metadata?.httpStatusCode
            log.warn({ bucket, key, status, err: (err as Error)?.message }, 'S3 upload failed')
            throw new RasterizationError(
                `S3 upload failed${status ? ` (status ${status})` : ''}: ${(err as Error)?.message ?? String(err)}`,
                true,
                'S3_UPLOAD_FAILED',
                err
            )
        }
        // Bucket, key and the raw body stay in this log line. The thrown message reaches team users as
        // ReplayObservation.error_reason, and the body is whatever an upstream proxy or gateway chose to
        // return, so only the status code goes into it. Retryability is untouched: the workflow's retry
        // policy keeps deciding, as it does for any other upload failure.
        log.warn(
            { bucket, key, status: undecodable.status, response_body: undecodable.body },
            'S3 upload returned an unreadable response'
        )
        throw new RasterizationError(
            `S3 upload failed: the object store returned an unreadable (non-XML) response (status ${undecodable.status ?? 'unknown'})`,
            true,
            'S3_UPLOAD_UNDECODABLE_RESPONSE',
            err
        )
    }

    return target
}
