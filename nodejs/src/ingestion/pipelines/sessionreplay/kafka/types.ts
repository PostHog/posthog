import { DateTime } from 'luxon'
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

// Ready-to-write JSONL lines plus per-event metadata from the native anonymizer.

// Per-event flag bits, mirroring `rust/replay-anonymizer-node/src/snapshot.rs` (EVENT_FLAG_*).
export const PRE_SERIALIZED_FLAG_ACTIVE = 1
export const PRE_SERIALIZED_FLAG_CLICK = 2
export const PRE_SERIALIZED_FLAG_KEYPRESS = 4
export const PRE_SERIALIZED_FLAG_MOUSE_ACTIVITY = 8

export const PreSerializedEventMetaSchema = z.object({
    ts: z.number(),
    flags: z.number(),
    href: z.string().optional(),
})

export const PreSerializedEventsSchema = z.object({
    lines: z.instanceof(Buffer),
    events: z.array(PreSerializedEventMetaSchema),
    consoleLogCount: z.number(),
    consoleWarnCount: z.number(),
    consoleErrorCount: z.number(),
})

export const ParsedMessageDataSchema = z.object({
    distinct_id: z.string(),
    session_id: z.string(),
    token: z.string().nullable(),
    eventsByWindowId: z.record(z.string(), z.array(SnapshotEventSchema)),
    eventsRange: EventsRangeSchema,
    snapshot_source: z.string().nullable(),
    snapshot_library: z.string().nullable(),
    metadata: MessageMetadataSchema,
    preSerialized: PreSerializedEventsSchema.optional(),
})

export type Event = z.infer<typeof EventSchema>
export type SnapshotEvent = z.infer<typeof SnapshotEventSchema>
export type PreSerializedEventMeta = z.infer<typeof PreSerializedEventMetaSchema>
export type PreSerializedEvents = z.infer<typeof PreSerializedEventsSchema>
export type ParsedMessageData = z.infer<typeof ParsedMessageDataSchema>
