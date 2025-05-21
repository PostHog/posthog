import { DateTime } from 'luxon'
import { MessageHeader } from 'node-rdkafka'
import { z } from 'zod'

const dateTimeSchema = z.custom<DateTime>((val) => val instanceof DateTime)

// This is the schema for the raw event message from Kafka

export const RawEventMessageSchema = z.object({
    distinct_id: z.string(),
    data: z.string(),
})

export type RawEventMessage = z.infer<typeof RawEventMessageSchema>

// This is the schema for the message metadata from Kafka

export const MessageMetadataSchema = z.object({
    partition: z.number(),
    topic: z.string(),
    rawSize: z.number(),
    offset: z.number(),
    timestamp: z.number(),
})

export type MessageMetadata = z.infer<typeof MessageMetadataSchema>

// The following schemas are for the parsed session recording events

const EventsRangeSchema = z.object({
    start: dateTimeSchema,
    end: dateTimeSchema,
})

const EventPropertiesSchema = z
    .object({
        $snapshot_items: z.array(z.unknown()).optional(),
        $session_id: z.string().optional(),
        $window_id: z.string().optional(),
        $snapshot_source: z.string().optional(),
        $lib: z.string().optional(),
    })
    .partial()
    .passthrough()

export const SnapshotEventSchema = z
    .object({
        timestamp: z.number(),
    })
    .passthrough()

export const EventSchema = z.object({
    event: z.string(),
    properties: EventPropertiesSchema,
})

export const ParsedMessageDataSchema = z.object({
    distinct_id: z.string(),
    session_id: z.string(),
    eventsByWindowId: z.record(z.string(), z.array(SnapshotEventSchema)),
    eventsRange: EventsRangeSchema,
    snapshot_source: z.string().nullable(),
    snapshot_library: z.string().nullable(),
    headers: z.array(z.custom<MessageHeader>()).optional(),
    metadata: MessageMetadataSchema,
})

export type Event = z.infer<typeof EventSchema>
export type SnapshotEvent = z.infer<typeof SnapshotEventSchema>
export type ParsedMessageData = z.infer<typeof ParsedMessageDataSchema>
