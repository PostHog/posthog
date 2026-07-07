/** Routes each parsed rrweb event to the right scrubber by type/source. */
import { logger } from '~/common/utils/logger'
import { ParsedMessageData } from '~/ingestion/pipelines/sessionreplay/kafka/types'
import { SessionRecordingIngesterMetrics } from '~/ingestion/pipelines/sessionreplay/metrics'
import { RRWebEventSource, RRWebEventType } from '~/ingestion/pipelines/sessionreplay/rrweb-types'

import { runBlurJobs } from './blur'
import { scrubCanvasMutation } from './canvas'
import { BlurCache, BlurJob, ScrubContext, ScrubTiming, isObject } from './config'
import { scrubCompressedFullSnapshot, scrubCompressedMutation } from './cv'
import { scrubFullSnapshot, scrubMutation } from './dom'
import { scrubText } from './text'
import { scrubUrl } from './url'
import { scrubConsolePlugin, scrubGenericField, scrubNetworkPlugin } from './value'

const NETWORK_PLUGIN = 'rrweb/network@1'
const CONSOLE_PLUGIN = 'rrweb/console@1'

const yieldToEventLoop = (): Promise<void> => new Promise((resolve) => setImmediate(resolve))

// Diagnostic: log the per-message time breakdown when a message takes longer than this to anonymize.
const ANON_SLOW_LOG_THRESHOLD_MS = 5000

/**
 * Anonymizes every event in a parsed message in place, then awaits its blur jobs.
 * Fails closed: returns `failed: true` if any event errors, so the caller can drop
 * the message rather than write un-anonymized data to the unencrypted ML bucket.
 */
export async function anonymizeParsedMessage(
    scrubContext: ScrubContext,
    parsedMessage: ParsedMessageData
): Promise<{ failed: boolean }> {
    const blurJobs: BlurJob[] = []
    // One memo per Kafka message: identical images across its rrweb events share a single sharp call.
    const blurCache: BlurCache = new Map()
    const timing: ScrubTiming = { decompressMs: 0, recompressMs: 0 }
    const ctx: ScrubContext = { ...scrubContext, blurJobs, blurCache, timing }

    const scrubStart = performance.now()
    let eventCount = 0
    for (const events of Object.values(parsedMessage.eventsByWindowId)) {
        for (const event of events) {
            try {
                anonymizeEvent(ctx, event)
            } catch (error) {
                logger.warn('🙈', 'anonymize_event_failed', {
                    error: String(error),
                    type: isObject(event) ? event.type : undefined,
                })
                SessionRecordingIngesterMetrics.incrementMlAnonymizeFailed('ts')
                return { failed: true }
            }
            eventCount++
        }
    }
    // scrubMs is synchronous (on the event loop); blurMs is the off-thread sharp work we await.
    const scrubMs = performance.now() - scrubStart

    const blurStart = performance.now()
    await runBlurJobs(blurJobs)
    const blurMs = performance.now() - blurStart

    SessionRecordingIngesterMetrics.observeMlAnonymizeDuration('ts', scrubMs + blurMs)

    if (scrubMs + blurMs > ANON_SLOW_LOG_THRESHOLD_MS) {
        logger.warn('🕒', 'anonymize_slow_breakdown', {
            totalMs: Math.round(scrubMs + blurMs),
            scrubMs: Math.round(scrubMs),
            blurMs: Math.round(blurMs),
            decompressMs: Math.round(timing.decompressMs),
            recompressMs: Math.round(timing.recompressMs),
            walkMs: Math.round(scrubMs - timing.decompressMs - timing.recompressMs),
            events: eventCount,
            blurJobs: blurJobs.length,
            sessionId: parsedMessage.session_id,
            topic: parsedMessage.metadata.topic,
            partition: parsedMessage.metadata.partition,
            offset: parsedMessage.metadata.offset,
            kafkaTimestamp: parsedMessage.metadata.timestamp,
            rawSize: parsedMessage.metadata.rawSize,
        })
    }

    // Macrotask break so a batch of messages doesn't scrub fully synchronously and starve the loop.
    await yieldToEventLoop()
    return { failed: false }
}

/**
 * Scrubs a single event in place, returning whether it changed. Throws if a
 * scrubber errors — callers must treat a throw as "could not anonymize", never
 * as "nothing to scrub".
 */
export function anonymizeEvent(ctx: ScrubContext, event: unknown): boolean {
    if (!isObject(event)) {
        return false
    }
    return routeEvent(ctx, event)
}

function routeEvent(ctx: ScrubContext, event: Record<string, unknown>): boolean {
    const compressed = event.cv != null
    const data = event.data

    switch (event.type) {
        case RRWebEventType.FullSnapshot:
            return compressed ? scrubCompressedFullSnapshot(ctx, event) : scrubFullSnapshot(ctx, data)

        case RRWebEventType.IncrementalSnapshot: {
            if (!isObject(data)) {
                return false
            }
            if (data.source === RRWebEventSource.Mutation) {
                return compressed ? scrubCompressedMutation(ctx, event) : scrubMutation(ctx, data)
            }
            if (data.source === RRWebEventSource.Input) {
                return scrubStringField(ctx, data, 'text', 'text')
            }
            if (data.source === RRWebEventSource.CanvasMutation) {
                return scrubCanvasMutation(ctx, data)
            }
            return false
        }

        case RRWebEventType.Meta: {
            // Meta `href` is the page URL — also strip the authority and rewrite the host to
            // example.com (Meta only for now).
            if (!isObject(data) || typeof data.href !== 'string') {
                return false
            }
            const r = scrubUrl(ctx, data.href, { collapseHost: true })
            if (r.changed) {
                data.href = r.value
                return true
            }
            return false
        }

        case RRWebEventType.Custom:
            return isObject(data) ? scrubGenericField(ctx, data, 'payload') : false

        case RRWebEventType.Plugin: {
            if (!isObject(data)) {
                return false
            }
            if (data.plugin === NETWORK_PLUGIN) {
                return scrubNetworkPlugin(ctx, data, 'payload')
            }
            if (data.plugin === CONSOLE_PLUGIN) {
                return scrubConsolePlugin(ctx, data, 'payload')
            }
            return scrubGenericField(ctx, data, 'payload')
        }

        default:
            // DomContentLoaded, Load, unknown types: pass-through.
            return false
    }
}

function scrubStringField(
    ctx: ScrubContext,
    owner: Record<string, unknown>,
    key: string,
    kind: 'text' | 'url'
): boolean {
    const value = owner[key]
    if (typeof value !== 'string') {
        return false
    }
    const result = kind === 'url' ? scrubUrl(ctx, value) : scrubText(ctx, value)
    if (result.changed) {
        owner[key] = result.value
        return true
    }
    return false
}
