import {
    ErrorTrackingException,
    ErrorTrackingStackFrame,
    ErrorTrackingStackFrameRecord,
} from 'lib/components/Errors/types'
import { uuid } from 'lib/utils'

import { EventType } from '~/types'

import { TEST_EVENTS } from '../events'

function collectFrameRawIdsFromException(exc: ErrorTrackingException): ErrorTrackingStackFrame[] {
    return exc.stacktrace?.frames.flatMap((frame) => frame) || []
}

function collectFrameRawIdsFromEvent(event: EventType): ErrorTrackingStackFrame[] {
    const exceptionList = (event.properties['$exception_list'] || []) as ErrorTrackingException[]
    return exceptionList.flatMap(collectFrameRawIdsFromException)
}

const frames = Object.values(TEST_EVENTS)
    .flatMap((event) => collectFrameRawIdsFromEvent(event as unknown as EventType))
    .flat()

function generateFrameContext(frame: ErrorTrackingStackFrame): ErrorTrackingStackFrameRecord {
    return {
        id: uuid(),
        raw_id: frame.raw_id,
        created_at: '2025-04-21T22:02:15.122000Z',
        resolved: true,
        context: {
            before: [
                {
                    line: 'const frameIds = Object.values(EVENTS).flatMap((event) => collectFrameRawIdsFromEvent(event as unknown as EventType))',
                    number: 9,
                },
            ],
            line: {
                line: 'function generateFrameContext(frameId: string): ErrorTrackingStackFrameRecord',
                number: 10,
            },
            after: [
                {
                    line: 'export const results: ErrorTrackingStackFrameRecord[] = frameIds.map()',
                    number: 11,
                },
            ],
        },
        contents: frame,
        symbol_set_ref: '123123',
        release: null,
    }
}

export const results: ErrorTrackingStackFrameRecord[] = frames.map(generateFrameContext)
