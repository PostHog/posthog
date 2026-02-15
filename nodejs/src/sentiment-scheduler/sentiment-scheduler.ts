/**
 * Sentiment Scheduler
 *
 * Consumes $ai_generation events from the main events stream and triggers
 * sentiment classification workflows via Temporal. Uses deterministic sampling
 * controlled by a PostHog feature flag payload (`llm-analytics-sentiment-rollout`)
 * so the sample rate can be changed from the PostHog UI without a deploy.
 *
 * Separate from the evaluation scheduler — sentiment runs a local HuggingFace
 * model (free, fast) rather than an external LLM API.
 */
import * as crypto from 'crypto'
import { Message } from 'node-rdkafka'
import { PostHog } from 'posthog-node'
import { Counter, Gauge } from 'prom-client'

import { KAFKA_EVENTS_JSON, prefix as KAFKA_PREFIX } from '../config/kafka-topics'
import { KafkaConsumer } from '../kafka/consumer'
import { TemporalService, TemporalServiceHub } from '../llm-analytics/services/temporal.service'
import { Hub, PluginServerService, RawKafkaEvent } from '../types'
import { parseJSON } from '../utils/json-parse'
import { logger } from '../utils/logger'

/** Narrowed Hub type for sentiment scheduler */
export type SentimentSchedulerHub = TemporalServiceHub &
    Pick<
        Hub,
        | 'LLMA_SENTIMENT_BATCH_SIZE'
        | 'LLMA_SENTIMENT_FLUSH_INTERVAL_MS'
        | 'LLMA_SENTIMENT_SAMPLE_RATE'
        | 'LLMA_SENTIMENT_TEAM_IDS'
        | 'POSTHOG_API_KEY'
        | 'POSTHOG_HOST_URL'
    >

const FEATURE_FLAG_KEY = 'llm-analytics-sentiment-rollout'
const FLAG_POLL_INTERVAL_MS = 30_000
const FLAG_DISTINCT_ID = 'llma-sentiment-scheduler'

/** Default sample rate (1%) — used when feature flag is unavailable */
const DEFAULT_SAMPLE_RATE = 0.01

const sentimentSchedulerMessagesReceived = new Counter({
    name: 'llma_sentiment_scheduler_messages_received',
    help: 'Number of Kafka messages received before filtering',
})

const sentimentSchedulerEventsFiltered = new Counter({
    name: 'llma_sentiment_scheduler_events_filtered',
    help: 'Number of events after productTrack header filter',
    labelNames: ['passed'],
})

const sentimentSchedulerEventsProcessed = new Counter({
    name: 'llma_sentiment_scheduler_events_processed',
    help: 'Number of events processed by sentiment scheduler',
    labelNames: ['status'], // sampled_in, sampled_out, success, error
})

const sentimentSchedulerBatchesStarted = new Counter({
    name: 'llma_sentiment_scheduler_batches_started',
    help: 'Number of batch workflows started by sentiment scheduler',
    labelNames: ['status'], // success, error
})

const sentimentSchedulerTeamFiltered = new Counter({
    name: 'llma_sentiment_scheduler_team_filtered',
    help: 'Number of events filtered out by team allowlist',
})

const sentimentSchedulerSampleRate = new Gauge({
    name: 'llma_sentiment_scheduler_sample_rate',
    help: 'Current sample rate used by the sentiment scheduler',
})

const sentimentSchedulerBufferSize = new Gauge({
    name: 'llma_sentiment_scheduler_buffer_size',
    help: 'Current number of events in the flush buffer',
})

const sentimentSchedulerFlushes = new Counter({
    name: 'llma_sentiment_scheduler_flushes',
    help: 'Number of buffer flushes',
    labelNames: ['trigger'], // size, timer, shutdown
})

const DEFAULT_BATCH_SIZE = 100
const DEFAULT_FLUSH_INTERVAL_MS = 30_000

// Pure functions for testability

export function chunk<T>(arr: T[], size: number): T[][] {
    const chunks: T[][] = []
    for (let i = 0; i < arr.length; i += size) {
        chunks.push(arr.slice(i, i + size))
    }
    return chunks
}

export function parseTeamAllowlist(raw: string): Set<number> | null {
    if (!raw.trim()) {
        return null // empty = all teams allowed
    }
    const ids = new Set<number>()
    for (const part of raw.split(',')) {
        const id = parseInt(part.trim(), 10)
        if (!isNaN(id)) {
            ids.add(id)
        }
    }
    return ids.size > 0 ? ids : null
}

export function filterAndParseMessages(messages: Message[]): RawKafkaEvent[] {
    return messages
        .filter((message) => {
            const headers = message.headers as { productTrack?: Buffer }[] | undefined
            const productTrack = headers?.find((h) => h.productTrack)?.productTrack?.toString('utf8')
            return productTrack === 'llma'
        })
        .map((message) => {
            try {
                return parseJSON(message.value!.toString()) as RawKafkaEvent
            } catch (e) {
                logger.error('Error parsing event', { error: e })
                return null
            }
        })
        .filter((event): event is RawKafkaEvent => event !== null)
        .filter((event) => event.event === '$ai_generation')
}

export function checkSampleRate(eventId: string, sampleRate: number): boolean {
    if (sampleRate >= 1.0) {
        return true
    }
    if (sampleRate <= 0) {
        return false
    }

    // Deterministic sampling via MD5 hash
    const hash = crypto.createHash('md5').update(eventId).digest('hex')
    const hashValue = parseInt(hash.substring(0, 8), 16)
    const percentage = hashValue / 0xffffffff

    return percentage < sampleRate
}

export function parseSampleRatePayload(payload: unknown, fallback: number): number {
    if (payload === null || payload === undefined) {
        return fallback
    }

    let parsed: Record<string, unknown>
    if (typeof payload === 'string') {
        try {
            parsed = parseJSON(payload)
        } catch {
            return fallback
        }
    } else if (typeof payload === 'object') {
        parsed = payload as Record<string, unknown>
    } else {
        return fallback
    }

    const rate = Number(parsed.sample_rate)
    if (isNaN(rate) || rate < 0 || rate > 1) {
        return fallback
    }
    return rate
}

/**
 * Provides the current sample rate, polling a PostHog feature flag payload
 * periodically. Falls back to the env var / default if the flag is unavailable.
 */
export class SampleRateProvider {
    private currentRate: number
    private pollTimer: ReturnType<typeof setInterval> | null = null
    private posthogClient: PostHog | null = null

    constructor(
        private fallbackRate: number,
        private apiKey?: string,
        private hostUrl?: string
    ) {
        this.currentRate = fallbackRate
    }

    async start(): Promise<void> {
        if (this.apiKey) {
            this.posthogClient = new PostHog(this.apiKey, {
                host: this.hostUrl,
                enableExceptionAutocapture: false,
            })
            await this.refresh()
            this.pollTimer = setInterval(() => void this.refresh(), FLAG_POLL_INTERVAL_MS)
        } else {
            logger.info('No POSTHOG_API_KEY — using static sample rate', { sampleRate: this.fallbackRate })
        }
        sentimentSchedulerSampleRate.set(this.currentRate)
    }

    async refresh(): Promise<void> {
        if (!this.posthogClient) {
            return
        }
        try {
            const flagValue = await this.posthogClient.getFeatureFlag(FEATURE_FLAG_KEY, FLAG_DISTINCT_ID)
            if (flagValue === false) {
                // Flag is explicitly off — disable sampling
                this.currentRate = 0
            } else if (flagValue === undefined) {
                // Flag doesn't exist or SDK can't evaluate — use fallback
                this.currentRate = this.fallbackRate
            } else {
                const payload = await this.posthogClient.getFeatureFlagPayload(
                    FEATURE_FLAG_KEY,
                    FLAG_DISTINCT_ID,
                    flagValue
                )
                this.currentRate = parseSampleRatePayload(payload, this.fallbackRate)
            }
        } catch (error) {
            logger.warn('Failed to fetch sentiment sample rate flag, keeping current rate', {
                error: error instanceof Error ? error.message : String(error),
                currentRate: this.currentRate,
            })
        }
        sentimentSchedulerSampleRate.set(this.currentRate)
    }

    getSampleRate(): number {
        return this.currentRate
    }

    async stop(): Promise<void> {
        if (this.pollTimer) {
            clearInterval(this.pollTimer)
            this.pollTimer = null
        }
        if (this.posthogClient) {
            await this.posthogClient.shutdown()
            this.posthogClient = null
        }
    }
}

/**
 * Buffers sampled events and flushes to Temporal when the buffer reaches
 * batchSize or a periodic timer fires — whichever comes first.
 */
export class SentimentBatchBuffer {
    private buffer: RawKafkaEvent[] = []
    private flushTimer: ReturnType<typeof setInterval> | null = null

    constructor(
        private temporalService: TemporalService,
        private batchSize: number,
        private flushIntervalMs: number
    ) {}

    start(): void {
        this.flushTimer = setInterval(() => void this.flush('timer'), this.flushIntervalMs)
    }

    async add(events: RawKafkaEvent[]): Promise<void> {
        this.buffer.push(...events)
        sentimentSchedulerBufferSize.set(this.buffer.length)

        while (this.buffer.length >= this.batchSize) {
            const batch = this.buffer.splice(0, this.batchSize)
            sentimentSchedulerBufferSize.set(this.buffer.length)
            await this.dispatchBatch(batch, 'size')
        }
    }

    async flush(trigger: 'timer' | 'shutdown'): Promise<void> {
        if (this.buffer.length === 0) {
            return
        }

        const batches = chunk(this.buffer, this.batchSize)
        this.buffer = []
        sentimentSchedulerBufferSize.set(0)

        for (const batch of batches) {
            await this.dispatchBatch(batch, trigger)
        }
    }

    async stop(): Promise<void> {
        if (this.flushTimer) {
            clearInterval(this.flushTimer)
            this.flushTimer = null
        }
        await this.flush('shutdown')
    }

    getBufferSize(): number {
        return this.buffer.length
    }

    private async dispatchBatch(batch: RawKafkaEvent[], trigger: string): Promise<void> {
        try {
            await this.temporalService.startSentimentClassificationWorkflow(batch)
            sentimentSchedulerBatchesStarted.labels({ status: 'success' }).inc()
            sentimentSchedulerEventsProcessed.labels({ status: 'success' }).inc(batch.length)
            sentimentSchedulerFlushes.labels({ trigger }).inc()
            logger.info('Sentiment batch dispatched', { batchSize: batch.length, trigger })
        } catch (error: unknown) {
            logger.error('Error starting sentiment batch workflow', {
                eventCount: batch.length,
                trigger,
                error: error instanceof Error ? error.message : String(error),
            })
            sentimentSchedulerBatchesStarted.labels({ status: 'error' }).inc()
            sentimentSchedulerEventsProcessed.labels({ status: 'error' }).inc(batch.length)
        }
    }
}

export const startSentimentScheduler = async (hub: SentimentSchedulerHub): Promise<PluginServerService> => {
    logger.info('Starting sentiment scheduler')

    const temporalService = new TemporalService(hub)
    const fallbackRate = hub.LLMA_SENTIMENT_SAMPLE_RATE ?? DEFAULT_SAMPLE_RATE
    const teamAllowlist = parseTeamAllowlist(hub.LLMA_SENTIMENT_TEAM_IDS ?? '')
    const batchSize = hub.LLMA_SENTIMENT_BATCH_SIZE ?? DEFAULT_BATCH_SIZE

    const flushIntervalMs = hub.LLMA_SENTIMENT_FLUSH_INTERVAL_MS ?? DEFAULT_FLUSH_INTERVAL_MS

    const sampleRateProvider = new SampleRateProvider(fallbackRate, hub.POSTHOG_API_KEY, hub.POSTHOG_HOST_URL)
    await sampleRateProvider.start()

    const batchBuffer = new SentimentBatchBuffer(temporalService, batchSize, flushIntervalMs)
    batchBuffer.start()

    logger.info('Sentiment scheduler started', {
        sampleRate: sampleRateProvider.getSampleRate(),
        teamAllowlist: teamAllowlist ? Array.from(teamAllowlist) : 'all',
        batchSize,
        flushIntervalMs,
    })

    const kafkaConsumer = new KafkaConsumer({
        groupId: `${KAFKA_PREFIX}llma-sentiment-scheduler`,
        topic: KAFKA_EVENTS_JSON,
    })

    await kafkaConsumer.connect((messages) =>
        eachBatchSentimentScheduler(messages, batchBuffer, sampleRateProvider, teamAllowlist)
    )

    const onShutdown = async () => {
        await batchBuffer.stop()
        await sampleRateProvider.stop()
        await temporalService.disconnect()
        await kafkaConsumer.disconnect()
    }

    return {
        id: 'llma-sentiment-scheduler',
        healthcheck: () => kafkaConsumer.isHealthy(),
        onShutdown,
    }
}

export async function eachBatchSentimentScheduler(
    messages: Message[],
    batchBuffer: SentimentBatchBuffer,
    sampleRateProvider: SampleRateProvider,
    teamAllowlist?: Set<number> | null
): Promise<void> {
    sentimentSchedulerMessagesReceived.inc(messages.length)

    const aiGenerationEvents = filterAndParseMessages(messages)

    sentimentSchedulerEventsFiltered.labels({ passed: 'false' }).inc(messages.length - aiGenerationEvents.length)
    sentimentSchedulerEventsFiltered.labels({ passed: 'true' }).inc(aiGenerationEvents.length)

    if (aiGenerationEvents.length === 0) {
        return
    }

    // Filter by team allowlist when configured
    let eligibleEvents = aiGenerationEvents
    if (teamAllowlist) {
        eligibleEvents = aiGenerationEvents.filter((event) => teamAllowlist.has(event.team_id))
        sentimentSchedulerTeamFiltered.inc(aiGenerationEvents.length - eligibleEvents.length)
    }

    if (eligibleEvents.length === 0) {
        return
    }

    const sampleRate = sampleRateProvider.getSampleRate()
    const sampledEvents: RawKafkaEvent[] = []

    for (const event of eligibleEvents) {
        if (!checkSampleRate(event.uuid, sampleRate)) {
            sentimentSchedulerEventsProcessed.labels({ status: 'sampled_out' }).inc()
            continue
        }

        sentimentSchedulerEventsProcessed.labels({ status: 'sampled_in' }).inc()
        sampledEvents.push(event)
    }

    if (sampledEvents.length === 0) {
        return
    }

    await batchBuffer.add(sampledEvents)
}
