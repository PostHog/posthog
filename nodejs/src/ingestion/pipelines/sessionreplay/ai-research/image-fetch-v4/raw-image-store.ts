import { PutObjectCommand, S3Client, S3ServiceException } from '@aws-sdk/client-s3'
import { Counter } from 'prom-client'

import { ConcurrencyController } from '~/common/utils/concurrencyController'
import { sealV4Frame } from '~/ingestion/pipelines/sessionreplay/ai-research/v4-keys/frame'
import type { TeamDayKeys } from '~/ingestion/pipelines/sessionreplay/ai-research/v4-keys/team-day-keys'
import type { FetchCandidate } from '~/ingestion/pipelines/sessionreplay/ml-mirror-image-fetch/collected-urls-record'
import type { ImageFetchResult } from '~/ingestion/pipelines/sessionreplay/ml-mirror-image-fetch/image-fetcher'
import type { FetchedImageSink } from '~/ingestion/pipelines/sessionreplay/ml-mirror-image-fetch/image-sink'
import { ImageFetchProcessingMetrics } from '~/ingestion/pipelines/sessionreplay/ml-mirror-image-fetch/processing-metrics'
import { parseV4UrlRef } from '~/ingestion/pipelines/sessionreplay/ml-mirror-image-scrub/content-ref'
import {
    InvalidImageTransportError,
    prepareFetchedImage,
} from '~/ingestion/pipelines/sessionreplay/ml-mirror-image-scrub/image-transport'

const S3_WRITE_TIMEOUT_MS = 30_000

const storedImages = new Counter({
    name: 'ai_research_image_fetch_v4_stored_images_total',
    help: 'Fetched images the v4 lane handled, by outcome.',
    labelNames: ['outcome'],
})

/**
 * Stores each fetched image sealed and unscrubbed in `images-v4`, under the team day key of its reference. The v4
 * dataset is anonymized downstream, so unlike the v3 lane this sink never sends an image to the scrub lane.
 */
export class RawImageStore implements FetchedImageSink {
    private readonly writes: ConcurrencyController

    constructor(
        private readonly keys: Pick<TeamDayKeys, 'get'>,
        private readonly s3: Pick<S3Client, 'send'>,
        private readonly bucket: string,
        maxConcurrentWrites: number
    ) {
        if (!Number.isInteger(maxConcurrentWrites) || maxConcurrentWrites < 1) {
            throw new Error('the v4 image store needs a positive write limit')
        }
        this.writes = new ConcurrencyController(maxConcurrentWrites)
    }

    /** Bounds images held in memory while S3 is slow, as the v3 lane bounds its image publishes. */
    public async publishImage(candidate: FetchCandidate, result: ImageFetchResult): Promise<void> {
        await ImageFetchProcessingMetrics.runLimited(this.writes, 'image_publish_admission', 'image_publish_delivery', {
            debugTag: candidate.registrableDomain,
            fn: () => this.store(candidate, result),
        })
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
        const { teamId, keyDay, hash } = ref
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
        const key = await this.keys.get(teamId, keyDay)
        if (key.status !== 'ok') {
            storedImages.labels(key.status === 'deleted' ? 'deleted' : 'missing_key').inc()
            return
        }
        const objectKey = `images/url/dt=${keyDay}/${teamId}/${hash}`
        const frame = sealV4Frame(
            key.key,
            { teamId, keyDay, kind: 'image-url', codec: 'none', ref: candidate.originalRef },
            image
        )
        try {
            await this.s3.send(
                new PutObjectCommand({ Bucket: this.bucket, Key: objectKey, Body: frame, IfNoneMatch: '*' }),
                { abortSignal: AbortSignal.timeout(S3_WRITE_TIMEOUT_MS) }
            )
            storedImages.labels('stored').inc()
        } catch (error) {
            // The first write of a reference stands, so a repeated fetch of it is already stored.
            if (error instanceof S3ServiceException && error.$metadata.httpStatusCode === 412) {
                storedImages.labels('already_stored').inc()
                return
            }
            throw error
        }
    }
}
