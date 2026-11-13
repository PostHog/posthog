import { CopyObjectCommand, GetObjectCommand, PutObjectCommand, S3Client, S3ServiceException } from '@aws-sdk/client-s3'
import { Counter } from 'prom-client'

import { ConcurrencyController } from '~/common/utils/concurrencyController'
import type { TeamMonthKeys } from '~/ingestion/pipelines/sessionreplay/ai-research/v4-keys/team-month-keys'

import type { FetchCandidate } from './collected-urls-record'
import { PackedImageLocation, UrlCrawlHistoryItem, packOfStoredCopy } from './crawl-history'
import type { ImageFetchResult } from './image-fetcher'
import { ImagePacker, rowsOnTime } from './image-packer'
import type { RefreshingImageSink, StoredImage } from './image-sink'
import { InvalidImageTransportError } from './image-transport'
import { ImageFetchProcessingMetrics } from './processing-metrics'
import { URL_ASSET_RULES } from './url-asset-rules'
import { V4UrlAsset, V4UrlRef, parseV4UrlRef, publicFontRefOf, sealFetchedImage } from './v4-native'

const S3_WRITE_TIMEOUT_MS = 30_000
const CONTENT_TYPE = 'application/octet-stream'

const storedImages = new Counter({
    name: 'ai_research_v4_image_fetch_stored_images_total',
    help: 'Fetched images and fonts the v4 lane handled, by asset and outcome.',
    labelNames: ['asset', 'outcome'],
})

/**
 * Stores each fetched image sealed and unscrubbed in `images-v4`, under the team month key of its reference. The v4
 * dataset is anonymized downstream, so unlike the v3 lane this sink never sends an image to the scrub lane.
 * A public font is the same public file for every team, so it is stored once and unsealed.
 *
 * With a packer, an image whose index rows reach every write day in time goes in a pack. Every other image, and every
 * font, is stored as the one object of its reference, which a reader finds without the index.
 *
 * S3 expires an object by its creation time, and blocks that reference an image are written all month. So a new fetch
 * overwrites the object of its reference, and `refreshImage` copies it onto itself to reset its age. A packed copy
 * cannot be copied alone, so its refresh writes its frame again, in a new pack.
 */
export class RawImageStore implements RefreshingImageSink {
    private readonly writes: ConcurrencyController

    constructor(
        private readonly keys: Pick<TeamMonthKeys, 'get'>,
        private readonly s3: Pick<S3Client, 'send'>,
        private readonly bucket: string,
        maxConcurrentWrites: number,
        private readonly packer?: ImagePacker
    ) {
        if (!Number.isInteger(maxConcurrentWrites) || maxConcurrentWrites < 1) {
            throw new Error('the v4 image store needs a positive write limit')
        }
        this.writes = new ConcurrencyController(maxConcurrentWrites)
    }

    /** Bounds images held in memory while S3 is slow. */
    public async publishImage(candidate: FetchCandidate, result: ImageFetchResult): Promise<StoredImage> {
        return await ImageFetchProcessingMetrics.runLimited(
            this.writes,
            'image_publish_admission',
            'image_publish_delivery',
            {
                debugTag: candidate.registrableDomain,
                fn: () => this.store(candidate, result),
            }
        )
    }

    public async refreshImage(
        candidate: FetchCandidate,
        history: UrlCrawlHistoryItem | undefined
    ): Promise<StoredImage | null> {
        const ref = parseV4UrlRef(candidate.originalRef)
        if (!ref) {
            storedImages.labels('unknown', 'foreign_ref').inc()
            return null
        }
        const pack = packOfStoredCopy(history)
        return await ImageFetchProcessingMetrics.runLimited(
            this.writes,
            'image_publish_admission',
            'image_publish_delivery',
            {
                debugTag: candidate.registrableDomain,
                fn: async () => {
                    if (pack && ref.scope === 'team') {
                        return await this.repack(candidate, ref, pack)
                    }
                    return (await this.copyOntoItself(ref.asset, objectKey(ref))) ? {} : null
                },
            }
        )
    }

    /** A reader finds a packed copy only through the index, so a late row is replaced by the object of its reference. */
    public async indexStoredImage(candidate: FetchCandidate, history: UrlCrawlHistoryItem): Promise<void> {
        const ref = parseV4UrlRef(candidate.originalRef)
        const pack = packOfStoredCopy(history)
        if (!ref || ref.scope !== 'team' || !pack) {
            return
        }
        // The job stays handled when this fails: the batch has nothing to retry it with, and the copy is still stored.
        await ImageFetchProcessingMetrics.runLimited(this.writes, 'image_publish_admission', 'image_publish_delivery', {
            debugTag: candidate.registrableDomain,
            fn: () =>
                this.makeReadable(candidate, ref, pack).catch(() => {
                    storedImages.labels(ref.asset, 'index_failed').inc()
                }),
        })
    }

    private async makeReadable(
        candidate: FetchCandidate,
        ref: Extract<V4UrlRef, { scope: 'team' }>,
        pack: PackedImageLocation
    ): Promise<void> {
        if (this.packer && rowsOnTime(candidate.writeDays, Date.now())) {
            await this.packer.indexCopy(ref, candidate.originalRef, pack, candidate.writeDays)
            storedImages.labels(ref.asset, 'indexed').inc()
            return
        }
        const frame = await this.readPacked(pack)
        if (!frame) {
            storedImages.labels(ref.asset, 'pack_missing').inc()
            return
        }
        await this.putObject(objectKey(ref), frame)
        storedImages.labels(ref.asset, 'unpacked').inc()
    }

    private async repack(
        candidate: FetchCandidate,
        ref: Extract<V4UrlRef, { scope: 'team' }>,
        pack: PackedImageLocation
    ): Promise<StoredImage | null> {
        const frame = await this.readPacked(pack)
        if (!frame) {
            storedImages.labels(ref.asset, 'refresh_not_stored').inc()
            return null
        }
        const stored = await this.place(candidate, ref, frame, pack.mime, pack.byteSize)
        storedImages.labels(ref.asset, stored.pack ? 'refreshed_packed' : 'refreshed_unpacked').inc()
        return stored
    }

    private async readPacked(pack: PackedImageLocation): Promise<Buffer | null> {
        try {
            const read = await this.s3.send(
                new GetObjectCommand({
                    Bucket: this.bucket,
                    Key: pack.key,
                    Range: `bytes=${pack.byteStart}-${pack.byteEnd}`,
                }),
                { abortSignal: AbortSignal.timeout(S3_WRITE_TIMEOUT_MS) }
            )
            const frame = Buffer.from(await read.Body!.transformToByteArray())
            if (frame.length !== pack.byteEnd - pack.byteStart + 1) {
                throw new Error('a packed image read returned the wrong length')
            }
            return frame
        } catch (error) {
            if (error instanceof S3ServiceException && error.$metadata.httpStatusCode === 404) {
                return null
            }
            throw error
        }
    }

    private async place(
        candidate: FetchCandidate,
        ref: Extract<V4UrlRef, { scope: 'team' }>,
        frame: Buffer,
        mime: string,
        byteSize: number
    ): Promise<StoredImage> {
        if (this.packer && ref.asset === 'image' && rowsOnTime(candidate.writeDays, Date.now())) {
            const pack = await this.packer.add({
                ref,
                reference: candidate.originalRef,
                frame,
                mime,
                byteSize,
                writeDays: candidate.writeDays,
            })
            if (pack) {
                return { pack }
            }
        }
        await this.putObject(objectKey(ref), frame)
        return {}
    }

    private async putObject(key: string, body: Buffer): Promise<void> {
        await this.s3.send(
            new PutObjectCommand({
                Bucket: this.bucket,
                Key: key,
                Body: body,
                ContentType: CONTENT_TYPE,
            }),
            { abortSignal: AbortSignal.timeout(S3_WRITE_TIMEOUT_MS) }
        )
    }

    private async copyOntoItself(asset: V4UrlAsset, objectKey: string): Promise<boolean> {
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
                storedImages.labels(asset, 'refresh_not_stored').inc()
                return false
            }
            throw error
        }
        storedImages.labels(asset, 'refreshed').inc()
        return true
    }

    private async store(candidate: FetchCandidate, result: ImageFetchResult): Promise<StoredImage> {
        const ref = parseV4UrlRef(candidate.originalRef)
        // A throw keeps the URL unfinished, and these inputs come back the same on every fetch.
        if (!ref) {
            storedImages.labels('unknown', 'foreign_ref').inc()
            return {}
        }
        const { asset } = ref
        if (!result.bytes) {
            storedImages.labels(asset, 'invalid').inc()
            return {}
        }
        // Every team reads this one object, so it must hold the file its reference names and not a redirect target.
        if (ref.scope === 'public' && publicFontRefOf(candidate.currentUrl) !== candidate.originalRef) {
            storedImages.labels(asset, 'not_public').inc()
            return {}
        }
        const rules = URL_ASSET_RULES[asset]
        let body: Buffer
        try {
            body = await rules.prepare(result.bytes, result.contentType, result.contentEncoding)
        } catch (error) {
            // A body that is not the image it claims to be is handled: fetching it again returns the same body.
            if (error instanceof InvalidImageTransportError) {
                storedImages.labels(asset, 'invalid').inc()
                return {}
            }
            throw error
        }
        if (ref.scope === 'public') {
            await this.putObject(objectKey(ref), body)
            storedImages.labels(asset, 'stored').inc()
            return {}
        }
        const key = await this.keys.get(ref.teamId, ref.keyMonth)
        if (key.status !== 'ok') {
            storedImages.labels(asset, key.status === 'deleted' ? 'deleted' : 'missing_key').inc()
            return {}
        }
        const frame = await sealFetchedImage(key.key, candidate.originalRef, body)
        const stored = await this.place(candidate, ref, frame, result.contentType ?? CONTENT_TYPE, body.length)
        storedImages.labels(asset, stored.pack ? 'packed' : 'stored').inc()
        return stored
    }
}

/** One object per reference. The month is the reference's key month, not the day it was fetched. */
function objectKey(ref: V4UrlRef): string {
    const prefix = URL_ASSET_RULES[ref.asset].objectKeyPrefix
    return ref.scope === 'public'
        ? `${prefix}/public/${ref.hash}`
        : `${prefix}/month=${ref.keyMonth}/${ref.teamId}/${ref.hash}`
}
