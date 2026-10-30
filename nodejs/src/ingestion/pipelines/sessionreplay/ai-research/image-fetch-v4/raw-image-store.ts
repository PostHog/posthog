import { CopyObjectCommand, PutObjectCommand, S3Client, S3ServiceException } from '@aws-sdk/client-s3'
import { Counter } from 'prom-client'

import { ConcurrencyController } from '~/common/utils/concurrencyController'
import { sealV4Frame } from '~/ingestion/pipelines/sessionreplay/ai-research/v4-keys/frame'
import type { TeamMonthKeys } from '~/ingestion/pipelines/sessionreplay/ai-research/v4-keys/team-month-keys'

import type { FetchCandidate } from './collected-urls-record'
import type { ImageFetchResult } from './image-fetcher'
import type { RefreshingImageSink } from './image-sink'
import { InvalidImageTransportError, prepareFetchedImage } from './image-transport'
import { ImageFetchProcessingMetrics } from './processing-metrics'
import { parseV4UrlRef } from './v4-url-ref'

const S3_WRITE_TIMEOUT_MS = 30_000
/** The `images-v4` lifecycle is 98 days: the 90-day raw window plus this interval and one day. */
const REFRESH_INTERVAL_MS = 7 * 24 * 60 * 60 * 1000
const CONTENT_TYPE = 'application/octet-stream'

const storedImages = new Counter({
    name: 'ai_research_v4_image_fetch_stored_images_total',
    help: 'Fetched images the v4 lane handled, by outcome.',
    labelNames: ['outcome'],
})

/**
 * Stores each fetched image sealed and unscrubbed in `images-v4`, under the team month key of its reference. The v4
 * dataset is anonymized downstream, so unlike the v3 lane this sink never sends an image to the scrub lane.
 *
 * S3 expires an object by its creation time, and blocks that reference an image are written all month. So a new fetch
 * overwrites the object of its reference, and `refreshImage` copies it onto itself to reset its age.
 */
export class RawImageStore implements RefreshingImageSink {
    public readonly refreshIntervalMs = REFRESH_INTERVAL_MS
    private readonly writes: ConcurrencyController

    constructor(
        private readonly keys: Pick<TeamMonthKeys, 'get'>,
        private readonly s3: Pick<S3Client, 'send'>,
        private readonly bucket: string,
        maxConcurrentWrites: number
    ) {
        if (!Number.isInteger(maxConcurrentWrites) || maxConcurrentWrites < 1) {
            throw new Error('the v4 image store needs a positive write limit')
        }
        this.writes = new ConcurrencyController(maxConcurrentWrites)
    }

    /** Bounds images held in memory while S3 is slow. */
    public async publishImage(candidate: FetchCandidate, result: ImageFetchResult): Promise<void> {
        await ImageFetchProcessingMetrics.runLimited(this.writes, 'image_publish_admission', 'image_publish_delivery', {
            debugTag: candidate.registrableDomain,
            fn: () => this.store(candidate, result),
        })
    }

    public async refreshImage(candidate: FetchCandidate): Promise<boolean> {
        const ref = parseV4UrlRef(candidate.originalRef)
        if (!ref) {
            storedImages.labels('foreign_ref').inc()
            return false
        }
        return await ImageFetchProcessingMetrics.runLimited(
            this.writes,
            'image_publish_admission',
            'image_publish_delivery',
            {
                debugTag: candidate.registrableDomain,
                fn: () => this.copyOntoItself(imageObjectKey(ref)),
            }
        )
    }

    private async copyOntoItself(objectKey: string): Promise<boolean> {
        try {
            await this.s3.send(
                new CopyObjectCommand({
                    Bucket: this.bucket,
                    Key: objectKey,
                    // S3 URL-decodes CopySource (unlike Key), so path segments must be percent-encoded.
                    CopySource: `${this.bucket}/${objectKey.split('/').map(encodeURIComponent).join('/')}`,
                    MetadataDirective: 'REPLACE',
                    ContentType: CONTENT_TYPE,
                }),
                { abortSignal: AbortSignal.timeout(S3_WRITE_TIMEOUT_MS) }
            )
        } catch (error) {
            // The fetch stored nothing for this reference, for example because the body was not an image.
            if (error instanceof S3ServiceException && error.$metadata.httpStatusCode === 404) {
                storedImages.labels('refresh_not_stored').inc()
                return false
            }
            throw error
        }
        storedImages.labels('refreshed').inc()
        return true
    }

    private async store(candidate: FetchCandidate, result: ImageFetchResult): Promise<void> {
        const ref = parseV4UrlRef(candidate.originalRef)
        // A throw keeps the URL unfinished, and these inputs come back the same on every fetch.
        if (!ref) {
            storedImages.labels('foreign_ref').inc()
            return
        }
        if (!result.bytes) {
            storedImages.labels('invalid').inc()
            return
        }
        const { teamId, keyMonth } = ref
        let image: Buffer
        try {
            image = await prepareFetchedImage(result.bytes, result.contentType, result.contentEncoding)
        } catch (error) {
            // A body that is not the image it claims to be is handled: fetching it again returns the same body.
            if (error instanceof InvalidImageTransportError) {
                storedImages.labels('invalid').inc()
                return
            }
            throw error
        }
        const key = await this.keys.get(teamId, keyMonth)
        if (key.status !== 'ok') {
            storedImages.labels(key.status === 'deleted' ? 'deleted' : 'missing_key').inc()
            return
        }
        const frame = sealV4Frame(
            key.key,
            { teamId, keyMonth, kind: 'image-url', codec: 'none', ref: candidate.originalRef },
            image
        )
        await this.s3.send(
            new PutObjectCommand({
                Bucket: this.bucket,
                Key: imageObjectKey(ref),
                Body: frame,
                ContentType: CONTENT_TYPE,
            }),
            { abortSignal: AbortSignal.timeout(S3_WRITE_TIMEOUT_MS) }
        )
        storedImages.labels('stored').inc()
    }
}

/** One object per reference. The month is the reference's key month, not the day it was fetched. */
function imageObjectKey(ref: { teamId: number; keyMonth: string; hash: string }): string {
    return `images/url/month=${ref.keyMonth}/${ref.teamId}/${ref.hash}`
}
