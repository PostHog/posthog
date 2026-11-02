import { GetObjectCommand, PutObjectCommand, S3Client } from '@aws-sdk/client-s3'
import { createHash } from 'crypto'
import { Counter } from 'prom-client'

import type { ImageFetchOptions, ImageFetchResult, ImageFetcher } from './image-fetcher'
import { InvalidImageTransportError, prepareFetchedFont } from './image-transport'
import { URL_ASSET_RULES } from './url-asset-rules'

const S3_TIMEOUT_MS = 5_000
const PUBLIC_FONT_HOSTS = new Set(['fonts.gstatic.com'])

const publicFontCopies = new Counter({
    name: 'ai_research_v4_image_fetch_public_font_copies_total',
    help: 'v4 font fetches from a public font host, by what the shared copy did.',
    labelNames: ['outcome'],
})

/**
 * A public font host serves each file at a versioned path whose bytes never change, so one unsealed copy serves every
 * team. The sink still seals each job's copy under its team key, and the runner checks robots.txt and tdmrep first.
 */
export class PublicFontCache implements ImageFetcher {
    constructor(
        private readonly inner: ImageFetcher,
        private readonly s3: Pick<S3Client, 'send'>,
        private readonly bucket: string
    ) {}

    public async fetch(url: string, options: ImageFetchOptions): Promise<ImageFetchResult> {
        // A reservation can refuse a response by its headers, which the copy does not keep.
        if (options.asset !== 'font' || options.tdmrepReservation || !isPublicFontHost(url)) {
            return await this.inner.fetch(url, options)
        }
        const key = publicFontKey(url)
        const copy = await this.read(key, url)
        if (copy) {
            return copy
        }
        const result = await this.inner.fetch(url, options)
        if (result.outcome === 'ok' && result.redirects === 0 && result.bytes) {
            await this.write(key, result.bytes, result.contentType, result.contentEncoding)
        }
        return result
    }

    private async read(key: string, url: string): Promise<ImageFetchResult | undefined> {
        try {
            const object = await this.s3.send(new GetObjectCommand({ Bucket: this.bucket, Key: key }), {
                abortSignal: AbortSignal.timeout(S3_TIMEOUT_MS),
            })
            const bytes = object.Body ? Buffer.from(await object.Body.transformToByteArray()) : undefined
            if (!bytes || !object.ContentType) {
                publicFontCopies.labels('unreadable').inc()
                return undefined
            }
            publicFontCopies.labels('reused').inc()
            return { outcome: 'ok', redirects: 0, currentUrl: url, status: 200, bytes, contentType: object.ContentType }
        } catch (error) {
            const missing = (error as { name?: string }).name === 'NoSuchKey'
            publicFontCopies.labels(missing ? 'missing' : 'unreadable').inc()
            return undefined
        }
    }

    /** Only a response that passes the font checks is kept, so the copy never serves a body the sink would refuse. */
    private async write(
        key: string,
        bytes: Buffer,
        contentType: string | undefined,
        contentEncoding: string | undefined
    ): Promise<void> {
        let body: Buffer
        try {
            body = await prepareFetchedFont(bytes, contentType, contentEncoding)
        } catch (error) {
            if (error instanceof InvalidImageTransportError) {
                publicFontCopies.labels('not_a_font').inc()
                return
            }
            throw error
        }
        try {
            await this.s3.send(
                new PutObjectCommand({ Bucket: this.bucket, Key: key, Body: body, ContentType: contentType }),
                {
                    abortSignal: AbortSignal.timeout(S3_TIMEOUT_MS),
                }
            )
            publicFontCopies.labels('stored').inc()
        } catch {
            publicFontCopies.labels('unwritable').inc()
        }
    }
}

function isPublicFontHost(url: string): boolean {
    try {
        return PUBLIC_FONT_HOSTS.has(new URL(url).hostname)
    } catch {
        return false
    }
}

/** Under the font prefix, whose write grant the fetcher's role already has. */
export function publicFontKey(url: string): string {
    return `${URL_ASSET_RULES.font.objectKeyPrefix}/public/${createHash('sha256').update(url).digest('hex')}`
}
