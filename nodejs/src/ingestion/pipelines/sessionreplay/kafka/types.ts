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

// Pre-serialized scrubbed events, produced by the native anonymizer (`@posthog/replay-anonymizer`)
// when the ml-mirror pipeline runs the fused parse+anonymize step: the block lines are already JSONL
// `[windowId, event]` records, and the per-event metadata carries what the recorders would otherwise
// derive from parsed events. Messages carrying `preSerialized` have an empty `eventsByWindowId`.

// Per-event flag bits, mirroring `rust/replay-anonymizer-node/src/snapshot.rs` (EVENT_FLAG_*).
export const PRE_SERIALIZED_FLAG_ACTIVE = 1
export const PRE_SERIALIZED_FLAG_CLICK = 2
export const PRE_SERIALIZED_FLAG_KEYPRESS = 4
export const PRE_SERIALIZED_FLAG_MOUSE_ACTIVITY = 8

export const PreSerializedEventMetaSchema = z.object({
    /** The event's `timestamp` (epoch ms; can be fractional). */
    ts: z.number(),
    /** Bitmask of the PRE_SERIALIZED_FLAG_* bits. */
    flags: z.number(),
    /** Post-scrub `hrefFrom(event)`, when present. */
    href: z.string().optional(),
})

export const PreSerializedEventsSchema = z.object({
    /** Scrubbed JSONL block lines (`["<windowId>",<event>]\n` per valid event), ready to write. */
    lines: z.instanceof(Buffer),
    /** Per emitted line, in line order. */
    events: z.array(PreSerializedEventMetaSchema),
    /** rrweb/console@1 plugin events by level. */
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
