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

/**
 * Serializes one parsed message into the per-message session data the recorder aggregates:
 * the JSONL block chunks plus the counts, urls, and segmentation events derived from the events.
 * Handles both parsed events and the native anonymizer's pre-serialized fast path.
 */
export function serializeSessionData(message: ParsedMessageData): SerializedSessionData {
    const base = {
        eventsRange: { start: message.eventsRange.start, end: message.eventsRange.end },
        distinctId: message.distinct_id,
        snapshotSource: (message.snapshot_source || 'web').slice(0, MAX_SNAPSHOT_FIELD_LENGTH),
        snapshotLibrary: message.snapshot_library ? message.snapshot_library.slice(0, MAX_SNAPSHOT_FIELD_LENGTH) : null,
    }

    if (message.preSerialized) {
        // The native anonymizer already serialized the block lines; the counts, segmentation, and
        // urls come from the per-event metadata instead of walking parsed events.
        const { lines, events } = message.preSerialized
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
            ...base,
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

    const chunks: Buffer[] = []
    const segmentationEvents: SegmentationEvent[] = []
    const urls: string[] = []
    let rawBytes = 0
    let eventCount = 0
    let clickCount = 0
    let keypressCount = 0
    let mouseActivityCount = 0
    for (const [windowId, events] of Object.entries(message.eventsByWindowId)) {
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
        ...base,
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

export interface SerializeSessionStepInput {
    team: TeamForReplay
    parsedMessage: ParsedMessageData
    retentionPeriod: RetentionPeriod
    sessionKey: SessionKey
}

export interface SerializeSessionStepOutput {
    session: SessionRef
    data: SerializedSessionData
}

/**
 * Derives the per-message session block data from a parsed message: the session it belongs to
 * (with the retention and encryption key resolved upstream) and the serialized block chunks with
 * their counts. Pure business logic — the record step aggregates the result into the session
 * batch without looking at the raw events again.
 */
export function createSerializeSessionStep<T extends SerializeSessionStepInput>(): ProcessingStep<
    T,
    T & SerializeSessionStepOutput
> {
    return function serializeSessionStep(input) {
        const { team, parsedMessage, retentionPeriod, sessionKey } = input
        const session: SessionRef = {
            teamId: team.teamId,
            sessionId: parsedMessage.session_id,
            partition: parsedMessage.metadata.partition,
            retentionPeriod,
            sessionKey,
        }
        return Promise.resolve(
            ok({
                ...input,
                session,
                data: serializeSessionData(parsedMessage),
            })
        )
    }
}
