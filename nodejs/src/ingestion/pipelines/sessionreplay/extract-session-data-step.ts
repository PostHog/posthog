import { ok } from '~/ingestion/framework/results'
import { ProcessingStep } from '~/ingestion/framework/steps'
import {
    PRE_SERIALIZED_FLAG_ACTIVE,
    PRE_SERIALIZED_FLAG_CLICK,
    PRE_SERIALIZED_FLAG_KEYPRESS,
    PRE_SERIALIZED_FLAG_MOUSE_ACTIVITY,
    ParsedMessageData,
} from '~/ingestion/pipelines/sessionreplay/kafka/types'
import { hrefFrom, isClick, isKeypress, isMouseActivity } from '~/ingestion/pipelines/sessionreplay/rrweb-types'
import { SegmentationEvent, toSegmentationEvent } from '~/ingestion/pipelines/sessionreplay/segmentation'
import { SessionRef } from '~/ingestion/pipelines/sessionreplay/sessions/session-batch-recorder'
import { SerializedSessionData } from '~/ingestion/pipelines/sessionreplay/sessions/snappy-session-recorder'
import { RetentionPeriod } from '~/ingestion/pipelines/sessionreplay/shared/constants'
import { SessionKey } from '~/ingestion/pipelines/sessionreplay/shared/types'
import { TeamForReplay } from '~/ingestion/pipelines/sessionreplay/teams/types'

const MAX_SNAPSHOT_FIELD_LENGTH = 1000

/** The event-derived half of {@link SerializedSessionData} — everything but the message-level fields. */
type ExtractedEventData = Pick<
    SerializedSessionData,
    | 'chunks'
    | 'rawBytes'
    | 'eventCount'
    | 'segmentationEvents'
    | 'urls'
    | 'clickCount'
    | 'keypressCount'
    | 'mouseActivityCount'
>

/** Serializes parsed events into JSONL chunks and derives the counts, urls, and segmentation events. */
function serializeEvents(eventsByWindowId: ParsedMessageData['eventsByWindowId']): ExtractedEventData {
    const chunks: Buffer[] = []
    const segmentationEvents: SegmentationEvent[] = []
    const urls: string[] = []
    let rawBytes = 0
    let eventCount = 0
    let clickCount = 0
    let keypressCount = 0
    let mouseActivityCount = 0
    for (const [windowId, events] of Object.entries(eventsByWindowId)) {
        for (const event of events) {
            const serializedLine = JSON.stringify([windowId, event]) + '\n'
            const chunk = Buffer.from(serializedLine)
            chunks.push(chunk)
            rawBytes += chunk.length

            segmentationEvents.push(toSegmentationEvent(event))

            const eventUrl = hrefFrom(event)
            if (eventUrl) {
                urls.push(eventUrl)
            }
            if (isClick(event)) {
                clickCount += 1
            }
            if (isKeypress(event)) {
                keypressCount += 1
            }
            if (isMouseActivity(event)) {
                mouseActivityCount += 1
            }
            eventCount++
        }
    }
    return {
        chunks,
        rawBytes,
        eventCount,
        segmentationEvents,
        urls,
        clickCount,
        keypressCount,
        mouseActivityCount,
    }
}

/** Derives the counts, urls, and segmentation events from the native anonymizer's per-event metadata. */
function extractPreSerializedEvents(
    preSerialized: NonNullable<ParsedMessageData['preSerialized']>
): ExtractedEventData {
    const { lines, events } = preSerialized
    const segmentationEvents: SegmentationEvent[] = []
    const urls: string[] = []
    let clickCount = 0
    let keypressCount = 0
    let mouseActivityCount = 0
    for (const event of events) {
        segmentationEvents.push({
            timestamp: event.ts,
            isActive: (event.flags & PRE_SERIALIZED_FLAG_ACTIVE) !== 0,
        })
        if (event.href) {
            urls.push(event.href)
        }
        if (event.flags & PRE_SERIALIZED_FLAG_CLICK) {
            clickCount += 1
        }
        if (event.flags & PRE_SERIALIZED_FLAG_KEYPRESS) {
            keypressCount += 1
        }
        if (event.flags & PRE_SERIALIZED_FLAG_MOUSE_ACTIVITY) {
            mouseActivityCount += 1
        }
    }
    return {
        chunks: [lines],
        rawBytes: lines.length,
        eventCount: events.length,
        segmentationEvents,
        urls,
        clickCount,
        keypressCount,
        mouseActivityCount,
    }
}

export interface ExtractSessionDataStepInput {
    team: TeamForReplay
    parsedMessage: ParsedMessageData
    retentionPeriod: RetentionPeriod
    sessionKey: SessionKey
}

export interface ExtractSessionDataStepOutput {
    session: SessionRef
    data: SerializedSessionData
}

/**
 * Derives the per-message session block data from a parsed message: the session it belongs to
 * (with the retention and encryption key resolved upstream) and the serialized block chunks with
 * their counts. Pure business logic — the record step aggregates the result into the session
 * batch without looking at the raw events again.
 */
export function createExtractSessionDataStep<T extends ExtractSessionDataStepInput>(): ProcessingStep<
    T,
    T & ExtractSessionDataStepOutput
> {
    return function extractSessionDataStep(input) {
        const { team, parsedMessage, retentionPeriod, sessionKey } = input

        const session: SessionRef = {
            teamId: team.teamId,
            sessionId: parsedMessage.session_id,
            partition: parsedMessage.metadata.partition,
            retentionPeriod,
            sessionKey,
        }

        // The native anonymizer already serialized the block lines; the counts, segmentation, and
        // urls come from the per-event metadata instead of walking parsed events.
        const eventData = parsedMessage.preSerialized
            ? extractPreSerializedEvents(parsedMessage.preSerialized)
            : serializeEvents(parsedMessage.eventsByWindowId)

        const data: SerializedSessionData = {
            ...eventData,
            eventsRange: { start: parsedMessage.eventsRange.start, end: parsedMessage.eventsRange.end },
            distinctId: parsedMessage.distinct_id,
            snapshotSource: (parsedMessage.snapshot_source || 'web').slice(0, MAX_SNAPSHOT_FIELD_LENGTH),
            snapshotLibrary: parsedMessage.snapshot_library
                ? parsedMessage.snapshot_library.slice(0, MAX_SNAPSHOT_FIELD_LENGTH)
                : null,
        }

        return Promise.resolve(ok({ ...input, session, data }))
    }
}
