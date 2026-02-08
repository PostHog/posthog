/**
 * Sentiment Scheduler
 *
 * Consumes $ai_generation events from the main events stream and triggers
 * sentiment classification workflows via Temporal. Uses simple random sampling
 * (no per-team evaluation conditions) to control volume.
 *
 * Separate from the evaluation scheduler — sentiment runs a local HuggingFace
 * model (free, fast) rather than an external LLM API.
 */
import * as crypto from 'crypto'
import { Message } from 'node-rdkafka'
import { Counter } from 'prom-client'

import { KAFKA_EVENTS_JSON, prefix as KAFKA_PREFIX } from '../config/kafka-topics'
import { KafkaConsumer } from '../kafka/consumer'
import { TemporalService, TemporalServiceHub } from '../llm-analytics/services/temporal.service'
import { Hub, PluginServerService, RawKafkaEvent } from '../types'
import { parseJSON } from '../utils/json-parse'
import { logger } from '../utils/logger'

/** Narrowed Hub type for sentiment scheduler */
export type SentimentSchedulerHub = TemporalServiceHub & Pick<Hub, 'LLMA_SENTIMENT_SAMPLE_RATE'>

/** Default sample rate (1%) — configurable via LLMA_SENTIMENT_SAMPLE_RATE env var */
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

// Pure functions for testability

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

export const startSentimentScheduler = async (hub: SentimentSchedulerHub): Promise<PluginServerService> => {
    logger.info('Starting sentiment scheduler')

    const temporalService = new TemporalService(hub)
    const sampleRate = hub.LLMA_SENTIMENT_SAMPLE_RATE ?? DEFAULT_SAMPLE_RATE

    logger.info('Sentiment scheduler sample rate', { sampleRate })

    const kafkaConsumer = new KafkaConsumer({
        groupId: `${KAFKA_PREFIX}llma-sentiment-scheduler`,
        topic: KAFKA_EVENTS_JSON,
    })

    await kafkaConsumer.connect((messages) => eachBatchSentimentScheduler(messages, temporalService, sampleRate))

    const onShutdown = async () => {
        await temporalService.disconnect()
        await kafkaConsumer.disconnect()
    }

    return {
        id: 'llma-sentiment-scheduler',
        healthcheck: () => kafkaConsumer.isHealthy(),
        onShutdown,
    }
}

async function eachBatchSentimentScheduler(
    messages: Message[],
    temporalService: TemporalService,
    sampleRate: number
): Promise<void> {
    sentimentSchedulerMessagesReceived.inc(messages.length)

    const aiGenerationEvents = filterAndParseMessages(messages)

    sentimentSchedulerEventsFiltered.labels({ passed: 'false' }).inc(messages.length - aiGenerationEvents.length)
    sentimentSchedulerEventsFiltered.labels({ passed: 'true' }).inc(aiGenerationEvents.length)

    if (aiGenerationEvents.length === 0) {
        return
    }

    const tasks: Promise<void>[] = []

    for (const event of aiGenerationEvents) {
        if (!checkSampleRate(event.uuid, sampleRate)) {
            sentimentSchedulerEventsProcessed.labels({ status: 'sampled_out' }).inc()
            continue
        }

        sentimentSchedulerEventsProcessed.labels({ status: 'sampled_in' }).inc()

        const task = temporalService
            .startSentimentClassificationWorkflow(event)
            .then(() => {
                sentimentSchedulerEventsProcessed.labels({ status: 'success' }).inc()
            })
            .catch((error: unknown) => {
                logger.error('Error starting sentiment workflow', {
                    eventUuid: event.uuid,
                    error: error instanceof Error ? error.message : String(error),
                })
                sentimentSchedulerEventsProcessed.labels({ status: 'error' }).inc()
            })

        tasks.push(task)
    }

    await Promise.allSettled(tasks)
}
