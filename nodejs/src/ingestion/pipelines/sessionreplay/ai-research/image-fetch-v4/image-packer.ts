import { PutObjectCommand, S3Client } from '@aws-sdk/client-s3'
import { randomBytes } from 'node:crypto'
import { Counter } from 'prom-client'

import type { KafkaProducer } from '~/common/kafka/producer'

import type { PackedImageLocation } from './crawl-history'
import type { V4UrlRef } from './v4-native'

/**
 * A reader takes day D's index once the recorder's watermark files cover every row delivered before they were written.
 * The recorder rewrites them every few minutes until D ends, so a row sent this long before D ends is covered.
 */
export const ROW_CUTOFF_BEFORE_DAY_END_MS = 60 * 60 * 1000
const DAY_MS = 24 * 60 * 60 * 1000
const PACK_PREFIX = 'images/url/packs'
const CONTENT_TYPE = 'application/octet-stream'
const S3_WRITE_TIMEOUT_MS = 30_000
const MAX_SAFE_PACK_BYTES = 64 * 1024 * 1024

const packs = new Counter({
    name: 'ai_research_v4_image_fetch_packs_total',
    help: 'Image packs the v4 fetch lane wrote, and the images in them, by outcome.',
    labelNames: ['outcome'],
})

const indexRows = new Counter({
    name: 'ai_research_v4_image_fetch_index_rows_total',
    help: 'Image index rows the v4 fetch lane sent for packed images, by outcome.',
    labelNames: ['outcome'],
})

export interface ImagePackerOptions {
    index: Pick<KafkaProducer, 'produce'>
    indexTopic: string
    lingerMs: number
    maxPackBytes: number
    maxPackImages: number
    nowMs?: () => number
}

export interface PackEntry {
    ref: Extract<V4UrlRef, { scope: 'team' }>
    reference: string
    frame: Buffer
    mime: string
    byteSize: number
    writeDays: readonly string[]
}

interface Waiting extends PackEntry {
    resolve: (location: PackedImageLocation | undefined) => void
    reject: (error: unknown) => void
}

interface OpenPack {
    entries: Waiting[]
    bytes: number
    timer: NodeJS.Timeout
}

export function utcDay(ms: number): string {
    return new Date(ms).toISOString().slice(0, 10)
}

export function rowsOnTime(writeDays: readonly string[] | undefined, nowMs: number): writeDays is readonly string[] {
    return (
        writeDays !== undefined &&
        writeDays.length > 0 &&
        writeDays.every((day) => Date.parse(`${day}T00:00:00Z`) + DAY_MS - ROW_CUTOFF_BEFORE_DAY_END_MS > nowMs)
    )
}

/** A pack holds one team's images only, so a team's prefix holds only data sealed under that team's keys. */
export class ImagePacker {
    private readonly open = new Map<number, OpenPack>()
    private readonly nowMs: () => number

    constructor(
        private readonly s3: Pick<S3Client, 'send'>,
        private readonly bucket: string,
        private readonly options: ImagePackerOptions
    ) {
        if (!(options.lingerMs >= 0) || !(options.maxPackBytes > 0) || !(options.maxPackImages > 0)) {
            throw new Error('the image packer needs a linger, a byte limit and an image limit')
        }
        if (options.maxPackBytes > MAX_SAFE_PACK_BYTES) {
            throw new Error(`the image packer byte limit must be at most ${MAX_SAFE_PACK_BYTES}`)
        }
        this.nowMs = options.nowMs ?? Date.now
    }

    /** Resolves once the pack is stored and its rows delivered, or to undefined when the rows would be late. */
    public add(entry: PackEntry): Promise<PackedImageLocation | undefined> {
        return new Promise((resolve, reject) => {
            const teamId = entry.ref.teamId
            let pack = this.open.get(teamId)
            if (!pack) {
                pack = {
                    entries: [],
                    bytes: 0,
                    timer: setTimeout(() => void this.flush(teamId), this.options.lingerMs),
                }
                this.open.set(teamId, pack)
            }
            pack.entries.push({ ...entry, resolve, reject })
            pack.bytes += entry.frame.length
            if (pack.bytes >= this.options.maxPackBytes || pack.entries.length >= this.options.maxPackImages) {
                void this.flush(teamId)
            }
        })
    }

    public async indexCopy(
        ref: Extract<V4UrlRef, { scope: 'team' }>,
        reference: string,
        location: PackedImageLocation,
        writeDays: readonly string[]
    ): Promise<void> {
        await this.sendRows([{ ref, reference, writeDays, location }])
    }

    private async flush(teamId: number): Promise<void> {
        const pack = this.open.get(teamId)
        if (!pack) {
            return
        }
        this.open.delete(teamId)
        clearTimeout(pack.timer)
        const startedAtMs = this.nowMs()
        const onTime: Waiting[] = []
        for (const entry of pack.entries) {
            if (rowsOnTime(entry.writeDays, startedAtMs)) {
                onTime.push(entry)
            } else {
                entry.resolve(undefined)
            }
        }
        if (onTime.length === 0) {
            return
        }
        const key = `${PACK_PREFIX}/dt=${utcDay(startedAtMs)}/${teamId}/${startedAtMs}-${randomBytes(8).toString('hex')}`
        const placed: { entry: Waiting; byteStart: number; byteEnd: number }[] = []
        let offset = 0
        for (const entry of onTime) {
            placed.push({ entry, byteStart: offset, byteEnd: offset + entry.frame.length - 1 })
            offset += entry.frame.length
        }
        try {
            await this.s3.send(
                new PutObjectCommand({
                    Bucket: this.bucket,
                    Key: key,
                    Body: Buffer.concat(onTime.map((entry) => entry.frame)),
                    ContentType: CONTENT_TYPE,
                    IfNoneMatch: '*',
                }),
                { abortSignal: AbortSignal.timeout(S3_WRITE_TIMEOUT_MS) }
            )
            const storedAtMs = this.nowMs()
            const located = placed.map(({ entry, byteStart, byteEnd }) => ({
                entry,
                location: { key, byteStart, byteEnd, mime: entry.mime, byteSize: entry.byteSize, storedAtMs },
            }))
            await this.sendRows(
                located.map(({ entry, location }) => ({
                    ref: entry.ref,
                    reference: entry.reference,
                    writeDays: entry.writeDays,
                    location,
                }))
            )
            packs.labels('stored').inc()
            packs.labels('images').inc(onTime.length)
            for (const { entry, location } of located) {
                entry.resolve(location)
            }
        } catch (error) {
            packs.labels('failed').inc()
            for (const entry of onTime) {
                entry.reject(error)
            }
        }
    }

    private async sendRows(
        images: {
            ref: Extract<V4UrlRef, { scope: 'team' }>
            reference: string
            writeDays: readonly string[]
            location: PackedImageLocation
        }[]
    ): Promise<void> {
        const sends: Promise<void>[] = []
        for (const { ref, reference, writeDays, location } of images) {
            // The image index columns of replay-data.md, as the recorder writes them.
            const value = Buffer.from(
                JSON.stringify({
                    team_id: ref.teamId,
                    key_month: ref.keyMonth,
                    image_ref: reference,
                    pack_s3_key: location.key,
                    byte_start: location.byteStart,
                    byte_end: location.byteEnd,
                    mime: location.mime,
                    byte_size: location.byteSize,
                })
            )
            for (const day of writeDays) {
                sends.push(
                    this.options.index.produce({
                        topic: this.options.indexTopic,
                        key: Buffer.from(reference),
                        value,
                        headers: { 'ml-index': 'images', 'ml-write-day': day },
                    })
                )
            }
        }
        const outcomes = await Promise.allSettled(sends)
        const failed = outcomes.filter((outcome) => outcome.status === 'rejected')
        indexRows.labels('delivered').inc(outcomes.length - failed.length)
        if (failed.length > 0) {
            indexRows.labels('failed').inc(failed.length)
            throw (failed[0] as PromiseRejectedResult).reason
        }
    }
}
