import { PutObjectCommand } from '@aws-sdk/client-s3'
import { KafkaTopic, RecordingEvent, RecordingEventGroup, RecordingMessage } from './types'
import { s3Client } from './utils/s3'
import { meterProvider } from './utils/metrics'
import { performance } from 'perf_hooks'
import {
    convertKafkaMessageToRecordingMessage,
    convertRecordingMessageToKafkaMessage,
    getEventGroupDataString,
    getEventSize,
    getEventSummaryMetadata,
    getTopicAndPartitionFromKey,
    getTopicPartitionKey,
} from './utils/utils'
import { randomUUID } from 'crypto'
import { consumer, producer } from './utils/kafka'
import { config } from './config'
import { createLogger } from './utils/logger'

const logger = createLogger('ingester')

const maxEventGroupAge = Number.parseInt(
    process.env.MAX_EVENT_GROUP_AGE || process.env.NODE_ENV === 'dev' ? '1000' : '300000'
)
const eventGroupSizeUploadThreshold = Number.parseInt(
    process.env.MAX_EVENT_GROUP_SIZE || process.env.NODE_ENV === 'dev' ? '1000' : '1000000'
)

const RECORDING_EVENTS_DEAD_LETTER_TOPIC = config.topics.sessionRecordingEventsDeadLetter

type TopicConfig = {
    retryTopic: string
    timeout: number
}

const baseTopic = config.topics.sessionRecordingEvents

const RECORDING_EVENTS_TOPICS_CONFIGS: Record<KafkaTopic, TopicConfig> = {
    [`${baseTopic}`]: { timeout: 0, retryTopic: `${baseTopic}_retry_1` },
    [`${baseTopic}_retry_1`]: { timeout: 2 * 1000, retryTopic: `${baseTopic}_retry_2` },
    [`${baseTopic}_retry_2`]: { timeout: 30 * 1000, retryTopic: `${baseTopic}_retry_3` },
    [`${baseTopic}_retry_3`]: { timeout: 5 * 60 * 1000, retryTopic: RECORDING_EVENTS_DEAD_LETTER_TOPIC },
}
const RECORDING_EVENTS_TOPICS = Object.keys(RECORDING_EVENTS_TOPICS_CONFIGS) as KafkaTopic[]

// We hold multiple event groups per session at once. This is to avoid
// committing an offset for messages that haven't been sent yet.
const eventGroupsBySessionId: { [key: string]: RecordingEventGroup[] } = {}

// TODO: Handle old messages in this buffer. They could stop the Kafka offset from progressing
const eventBuffers: Record<string, RecordingEvent> = {}

// Define the metrics we'll be exposing at /metrics
const meter = meterProvider.getMeter('ingester')
const messagesReceived = meter.createCounter('messages_received')
const snapshotMessagesProcessed = meter.createCounter('snapshot_messages_processed')
const eventGroupsCommittedCounter = meter.createCounter('event_groups_committed')
const eventGroupsStarted = meter.createCounter('event_groups_started')
const eventGroupsInFlight = meter.createObservableGauge('event_groups_in_flight', {
    description: "Number of event groups that haven't been committed to S3 yet.",
})
const s3PutObjectTime = meter.createHistogram('s3_put_object_time')

// TODO: Handle transactions when retrying messages
const retryMessage = async (message: RecordingMessage): Promise<void> => {
    const retryTopic =
        RECORDING_EVENTS_TOPICS_CONFIGS[message.kafkaTopic as keyof typeof RECORDING_EVENTS_TOPICS_CONFIGS].retryTopic
    producer.send({
        topic: retryTopic,
        messages: [convertRecordingMessageToKafkaMessage(message)],
    })
}

const retryEventGroup = async (eventGroup: RecordingEventGroup): Promise<void> => {
    Object.values(eventGroup.events)
        .flat()
        .forEach((event) => {
            event.messages.forEach((message) => {
                retryMessage(message)
            })
        })
}

// TODO: Make this handle multiple topics + partitions
const getOffsetOfOldestMessageInBuffers = (topic: string, partition: number): number => {
    const oldestMessageOffsetInEventBufferForTopicAndPartition = Object.values(eventBuffers)
        .filter((event) => {
            return event.kafkaTopic === topic && event.kafkaPartition === partition
        })
        .reduce((acc, event) => {
            return Math.min(acc, event.oldestOffset)
        }, -1)

    const topicPartitionKey = getTopicPartitionKey(topic, partition)

    const oldestMessageOffsetInEventGroupsForTopicAndPartition = Object.values(eventGroupsBySessionId)
        .flat()
        .reduce((acc, eventGroup) => {
            return Math.min(acc, eventGroup.oldestOffsets[topicPartitionKey])
        }, -1)

    return Math.min(
        oldestMessageOffsetInEventBufferForTopicAndPartition,
        oldestMessageOffsetInEventGroupsForTopicAndPartition
    )
}

const commitEventGroupToS3 = async (eventGroupToSend: RecordingEventGroup): Promise<void> => {
    const baseKey = `session_recordings/team_id/${eventGroupToSend.teamId}/session_id/${eventGroupToSend.sessionId}`
    const dataKey = `${baseKey}/data/${eventGroupToSend.oldestEventTimestamp}-${eventGroupToSend.oldestOriginalOffset}`
    const metaDataEventSummaryKey = `${baseKey}/metadata/event_summaries/${eventGroupToSend.oldestEventTimestamp}-${eventGroupToSend.oldestOriginalOffset}`
    const metaDataKey = `${baseKey}/metadata/metadata.json`

    logger.debug({ action: 'committing_event_group', sessionId: eventGroupToSend.sessionId, key: dataKey })

    try {
        const sendStartTime = performance.now()
        await s3Client.send(
            new PutObjectCommand({
                Bucket: 'posthog',
                Key: metaDataEventSummaryKey,
                Body: getEventSummaryMetadata(eventGroupToSend),
            })
        )
        await s3Client.send(
            new PutObjectCommand({
                Bucket: 'posthog',
                Key: metaDataKey,
                Body: JSON.stringify({ distinctId: eventGroupToSend.distinctId }),
            })
        )
        await s3Client.send(
            new PutObjectCommand({
                Bucket: 'posthog',
                Key: dataKey,
                Body: getEventGroupDataString(eventGroupToSend),
            })
        )
        const sendEndTime = performance.now()
        s3PutObjectTime.record(sendEndTime - sendStartTime)
    } catch (err) {
        logger.error({
            action: 'failed_to_commit_event_group',
            sessionId: eventGroupToSend.sessionId,
            teamId: eventGroupToSend.teamId,
            key: dataKey,
            error: err,
        })
        retryEventGroup(eventGroupToSend)
    }

    // We've sent the event group to S3 or the retry queues, so we can remove it from the buffer
    eventGroupsBySessionId[eventGroupToSend.sessionId] = eventGroupsBySessionId[eventGroupToSend.sessionId].filter(
        (eventGroup) => {
            eventGroup.id !== eventGroupToSend.id
        }
    )

    eventGroupsInFlight.addCallback((observableResult) =>
        observableResult.observe(Object.keys(eventGroupsBySessionId).flat().length)
    )

    // Update the Kafka offsets for each topic/partition in the event group
    Object.keys(eventGroupToSend.oldestOffsets).forEach((topicPartitionKey) => {
        const { topic, partition } = getTopicAndPartitionFromKey(topicPartitionKey)
        const oldestOffsetInBuffers = getOffsetOfOldestMessageInBuffers(topic, partition)
        const offsetToCommit =
            oldestOffsetInBuffers === -1 ? eventGroupToSend.newestOffsets[topicPartitionKey] + 1 : oldestOffsetInBuffers
        consumer.commitOffsets([
            {
                topic,
                partition,
                offset: offsetToCommit.toString(),
            },
        ])
        logger.debug({ action: 'committing_offset', offset: offsetToCommit, partition, topic })
    })

    eventGroupsCommittedCounter.add(1)
}

const createEventGroup = (event: RecordingEvent): RecordingEventGroup => {
    const topicPartitionKey = getTopicPartitionKey(event.kafkaTopic, event.kafkaPartition)
    const eventGroup: RecordingEventGroup = {
        id: randomUUID(),
        events: [] as RecordingEvent[],
        size: 0,
        teamId: event.teamId,
        sessionId: event.sessionId,
        oldestEventTimestamp: event.timestamp,
        distinctId: event.distinctId,
        oldestOffsets: { [topicPartitionKey]: event.oldestOffset },
        newestOffsets: { [topicPartitionKey]: event.newestOffset },
        oldestOriginalOffset: event.oldestOriginalOffset,
        status: 'active',
    }
    eventGroup.timer = setTimeout(() => {
        eventGroup.status = 'sending'
        commitEventGroupToS3({ ...eventGroup })
    }, maxEventGroupAge)
    logger.debug({ action: 'create_event_group', sessionId: eventGroup.sessionId })

    if (eventGroupsBySessionId[event.sessionId]) {
        eventGroupsBySessionId[event.sessionId].push(eventGroup)
    } else {
        eventGroupsBySessionId[event.sessionId] = [eventGroup]
    }

    return eventGroup
}

const processCompleteEvent = async (event: RecordingEvent): Promise<void> => {
    logger.debug({
        action: 'process event',
        uuid: event.eventId,
        sessionId: event.sessionId,
    })

    let eventGroup = eventGroupsBySessionId[event.sessionId]?.filter((eventGroup) => eventGroup.status === 'active')[0]

    if (!eventGroup) {
        eventGroup = createEventGroup(event)
        eventGroupsStarted.add(1, { reason: 'no-existing-event-group' })
    }

    eventGroup.events.push(event)
    eventGroup.size += getEventSize(event)

    const topicPartitionKey = getTopicPartitionKey(event.kafkaTopic, event.kafkaPartition)

    eventGroup.newestOffsets[topicPartitionKey] = event.newestOffset
    if (eventGroup.oldestOffsets[topicPartitionKey] === undefined) {
        eventGroup.oldestOffsets[topicPartitionKey] = event.oldestOffset
    }

    eventGroup.oldestOriginalOffset = Math.min(eventGroup.oldestOriginalOffset, event.oldestOriginalOffset)

    if (eventGroup.size > eventGroupSizeUploadThreshold) {
        clearTimeout(eventGroup.timer)
        eventGroup.status = 'sending'
        commitEventGroupToS3({ ...eventGroup })
    }
}

const handleMessage = async (message: RecordingMessage): Promise<void> => {
    const recordingEvent: RecordingEvent = eventBuffers[message.eventId] || {
        eventId: message.eventId,
        sessionId: message.sessionId,
        windowId: message.windowId,
        distinctId: message.distinctId,
        eventSource: message.eventSource,
        eventType: message.eventType,
        teamId: message.teamId,
        timestamp: message.timestamp,
        complete: false,
        messages: [],
        kafkaTopic: message.kafkaTopic,
        kafkaPartition: message.kafkaPartition,
        oldestOffset: message.kafkaOffset,
        newestOffset: message.kafkaOffset,
        oldestOriginalOffset: message.originalKafkaOffset,
    }

    // Ensures that a single event only comes from a single topic and therefore a single partition (because the key is the sessionId)
    if (message.kafkaTopic === recordingEvent.kafkaTopic) {
        recordingEvent.complete = message.chunkIndex === message.chunkCount - 1
        recordingEvent.messages.push(message)
        recordingEvent.newestOffset = message.kafkaOffset
        if (!recordingEvent.complete) {
            eventBuffers[message.eventId] = recordingEvent
        } else {
            if (message.chunkCount !== recordingEvent.messages.length) {
                logger.error({
                    action: 'chunk_count_mismatch',
                    sessionId: message.sessionId,
                    eventId: message.eventId,
                    chunkCount: message.chunkCount,
                    chunkIndex: message.chunkIndex,
                    messageCount: recordingEvent.messages.length,
                })
            }
            processCompleteEvent(recordingEvent)
            delete eventBuffers[message.eventId]
        }

        snapshotMessagesProcessed.add(1)
    } else {
        logger.error({
            action: 'kafka_topic_mismatch',
            eventId: message.eventId,
            sessionId: message.sessionId,
            kafkaTopic: message.kafkaTopic,
            kafkaPartition: message.kafkaPartition,
            expectedKafkaTopic: recordingEvent.kafkaTopic,
            expectedKafkaPartition: recordingEvent.kafkaPartition,
        })
        producer.send({
            topic: RECORDING_EVENTS_DEAD_LETTER_TOPIC,
            messages: [convertRecordingMessageToKafkaMessage(message)],
        })
    }
}

export const startConsumer = (): void => {
    consumer.connect()
    consumer.subscribe({ topics: RECORDING_EVENTS_TOPICS })
    producer.connect()

    consumer.run({
        autoCommit: false,
        eachMessage: async ({ topic, partition, message }) => {
            // We need to parse the event to get team_id and session_id although
            // ideally we'd put this into the key instead to avoid needing to parse
            // TODO: handle seeking to first chunk offset
            // TODO: write data to file instead to reduce memory footprint
            // TODO: Handle duplicated data being stored in the case of a consumer restart
            messagesReceived.add(1)

            const recordingMessage = convertKafkaMessageToRecordingMessage(message, topic as KafkaTopic, partition)

            // TODO Do this without timeouts so order is maintained
            const timeout_ms = RECORDING_EVENTS_TOPICS_CONFIGS[topic as KafkaTopic].timeout
            if (timeout_ms !== 0) {
                setTimeout(() => {
                    handleMessage(recordingMessage)
                }, timeout_ms)
            } else {
                handleMessage(recordingMessage)
            }
        },
    })
}
